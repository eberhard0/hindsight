//! Hindsight time tracker: serves the app page and a JSON API backed by SQLite.
//! A drop-in replacement for `server.py` — same routes, environment variables,
//! database schema and responses, so either can run against the same database.
//!
//! Routes:
//!   GET  /            -> index.html
//!   GET  /api/items   -> {"items": [...]}   full state
//!   PUT  /api/items   -> replace full state (body: JSON array of things)
//!
//! Everything else is 404 — the SQLite file and seed.csv are never served.

use axum::{
    body::Bytes,
    extract::State,
    http::{header, HeaderMap, HeaderValue, Method, StatusCode, Uri},
    response::{IntoResponse, Response},
    Router,
};
use rusqlite::{params, types::Value as SqlValue, Connection};
use serde_json::{json, Map, Value};
use std::{
    collections::HashMap,
    path::{Path, PathBuf},
    sync::Arc,
};

const MAX_BODY: usize = 4 * 1024 * 1024;
/// Origins of the Capacitor Android/iOS WebView; the web app itself is same-origin.
const CORS_ORIGINS: [&str; 3] = ["https://localhost", "capacitor://localhost", "http://localhost"];

const ICON_MAP: &[(&str, &str)] = &[
    ("haircut|barber|hair", "✂️"), ("battery", "\u{1f50b}"),
    ("freon|^ac |ac clean|ac top", "❄️"), ("genset", "⚡"),
    ("tennis", "\u{1f3be}"), ("sheet", "\u{1f6cf}\u{fe0f}"), ("service|wax", "\u{1f527}"),
    ("gas|fuel|petrol|fill up", "⛽"), ("oil", "\u{1f6e2}\u{fe0f}"),
    ("dentist|teeth|tooth", "\u{1f9b7}"), ("doctor|checkup|clinic", "\u{1fa7a}"),
    ("gym|workout|run|exercise", "\u{1f3cb}\u{fe0f}"), ("tire|tyre", "\u{1f6de}"),
    ("laundry", "\u{1f9fa}"), ("clean", "\u{1f9f9}"), ("plant|water", "\u{1fab4}"),
    ("filter", "\u{1f32c}\u{fe0f}"), ("vitamin|pill|med", "\u{1f48a}"),
    ("call|phone", "\u{1f4de}"), ("bill|pay|rent", "\u{1f4b3}"),
    ("shave|beard", "\u{1fa92}"), ("nail", "\u{1f485}"),
    ("eye|glasses|lens", "\u{1f453}"), ("backup", "\u{1f4be}"),
    ("book|read", "\u{1f4d6}"), ("shop|grocer", "\u{1f6d2}"),
];

struct Config {
    root: PathBuf,
    db_path: PathBuf,
}

type Shared = Arc<Config>;

fn env_or(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}

#[tokio::main]
async fn main() {
    // ROOT is where index.html (and seed.csv) live. server.py used its own folder;
    // the binary defaults to the current directory, or HINDSIGHT_ROOT.
    let root = std::env::var("HINDSIGHT_ROOT")
        .map(PathBuf::from)
        .unwrap_or_else(|_| std::env::current_dir().expect("current dir"));
    let db_path = std::env::var("HINDSIGHT_DB")
        .map(PathBuf::from)
        .unwrap_or_else(|_| root.join("data").join("hindsight.db"));
    let port: u16 = env_or("HINDSIGHT_PORT", "8095").parse().expect("HINDSIGHT_PORT must be a port number");
    let bind = env_or("HINDSIGHT_BIND", "127.0.0.1");

    let config = Arc::new(Config { root, db_path });
    init_db(&config).expect("database init failed");

    let app = Router::new()
        .fallback(handle)
        .layer(axum::extract::DefaultBodyLimit::max(MAX_BODY))
        .with_state(config.clone());
    let addr = format!("{bind}:{port}");
    let listener = tokio::net::TcpListener::bind(&addr).await.expect("bind failed");
    println!("hindsight server on {addr}, db={}", config.db_path.display());
    axum::serve(listener, app)
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await
        .expect("server error");
}

// ---------------------------------------------------------------- database

fn connect(path: &Path) -> rusqlite::Result<Connection> {
    let conn = Connection::open(path)?;
    conn.busy_timeout(std::time::Duration::from_secs(5))?;
    // journal_mode answers with a row, which plain pragma_update rejects.
    conn.pragma_update_and_check(None, "journal_mode", "WAL", |_| Ok(()))?;
    conn.pragma_update(None, "foreign_keys", "ON")?;
    Ok(conn)
}

fn init_db(cfg: &Config) -> Result<(), Box<dyn std::error::Error>> {
    if let Some(dir) = cfg.db_path.parent() {
        std::fs::create_dir_all(dir)?;
    }
    let mut conn = connect(&cfg.db_path)?;
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS things(
           id    TEXT PRIMARY KEY,
           name  TEXT NOT NULL,
           icon  TEXT,
           cat   TEXT,
           every INTEGER,
           dueOn INTEGER,
           deleted INTEGER
         );
         CREATE TABLE IF NOT EXISTS logs(
           id       TEXT PRIMARY KEY,
           thing_id TEXT NOT NULL REFERENCES things(id) ON DELETE CASCADE,
           ts       INTEGER NOT NULL,
           note     TEXT NOT NULL DEFAULT ''
         );
         CREATE INDEX IF NOT EXISTS idx_logs_thing ON logs(thing_id, ts DESC);",
    )?;
    // migration for databases created before the trash feature
    let has_deleted = {
        let mut stmt = conn.prepare("PRAGMA table_info(things)")?;
        let cols: Vec<String> = stmt.query_map([], |r| r.get::<_, String>(1))?.collect::<Result<_, _>>()?;
        cols.iter().any(|c| c == "deleted")
    };
    if !has_deleted {
        conn.execute("ALTER TABLE things ADD COLUMN deleted INTEGER", [])?;
    }
    let count: i64 = conn.query_row("SELECT COUNT(*) FROM things", [], |r| r.get(0))?;
    let seed = cfg.root.join("seed.csv");
    if count == 0 && seed.exists() {
        let text = std::fs::read_to_string(&seed)?;
        let n = seed_from_csv(&mut conn, &text)?;
        println!("seeded database from seed.csv: {n} log entries");
    }
    Ok(())
}

fn short_id() -> String {
    uuid::Uuid::new_v4().simple().to_string()[..12].to_string()
}

fn guess_icon(name: &str) -> &'static str {
    let n = name.to_lowercase();
    for (pat, icon) in ICON_MAP {
        if regex::Regex::new(pat).map(|re| re.is_match(&n)).unwrap_or(false) {
            return *icon;
        }
    }
    "•"
}

/// Hindsight iOS export rows: Category,Event,Occurrence,Note (local time).
fn parse_occurrence(occ: &str) -> Option<i64> {
    use chrono::{Local, NaiveDateTime, TimeZone};
    let take = |n: usize| occ.chars().take(n).collect::<String>();
    let naive = NaiveDateTime::parse_from_str(&take(19), "%Y-%m-%d %H:%M:%S")
        .or_else(|_| NaiveDateTime::parse_from_str(&take(16), "%Y-%m-%d %H:%M"))
        .ok()?;
    Local.from_local_datetime(&naive).earliest().map(|dt| dt.timestamp_millis())
}

fn seed_from_csv(conn: &mut Connection, text: &str) -> Result<usize, Box<dyn std::error::Error>> {
    let mut reader = csv::ReaderBuilder::new()
        .has_headers(false)
        .flexible(true)
        .from_reader(text.as_bytes());
    let mut rows: Vec<Vec<String>> = Vec::new();
    for rec in reader.records() {
        rows.push(rec?.iter().map(|s| s.to_string()).collect());
    }
    if rows.first().and_then(|r| r.first()).map(|c| c.to_lowercase().contains("category")).unwrap_or(false) {
        rows.remove(0);
    }
    let strip = regex::Regex::new("[^a-z0-9]").unwrap();
    let mut order: Vec<String> = Vec::new();
    let mut things: HashMap<String, Map<String, Value>> = HashMap::new();
    let mut count = 0;
    for row in rows {
        if row.len() < 3 {
            continue;
        }
        let (cat, name, occ) = (row[0].trim(), row[1].trim(), row[2].trim());
        let note = row.get(3).map(|s| s.trim()).unwrap_or("");
        if name.is_empty() || occ.is_empty() {
            continue;
        }
        let Some(ts) = parse_occurrence(occ) else { continue };
        let key = strip.replace_all(&name.to_lowercase(), "").to_string();
        let thing = things.entry(key.clone()).or_insert_with(|| {
            order.push(key.clone());
            let mut t = Map::new();
            t.insert("id".into(), json!(short_id()));
            t.insert("name".into(), json!(name));
            t.insert("icon".into(), json!(guess_icon(name)));
            t.insert("cat".into(), if cat.is_empty() { Value::Null } else { json!(cat) });
            t.insert("every".into(), Value::Null);
            t.insert("dueOn".into(), Value::Null);
            t.insert("log".into(), json!([]));
            t
        });
        if let Some(Value::Array(log)) = thing.get_mut("log") {
            log.push(json!({"id": short_id(), "ts": ts, "note": note}));
        }
        count += 1;
    }
    let items: Vec<Value> = order.into_iter().filter_map(|k| things.remove(&k)).map(Value::Object).collect();
    write_items(conn, &items)?;
    Ok(count)
}

/// Python's str(): strings as-is, everything else in its JSON form.
fn py_str(v: &Value) -> String {
    match v {
        Value::String(s) => s.clone(),
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        other => other.to_string(),
    }
}

/// A JSON value stored as-is in a loosely typed SQLite column.
fn to_sql(v: Option<&Value>) -> SqlValue {
    match v {
        None | Some(Value::Null) => SqlValue::Null,
        Some(Value::Bool(b)) => SqlValue::Integer(*b as i64),
        Some(Value::Number(n)) => n
            .as_i64()
            .map(SqlValue::Integer)
            .or_else(|| n.as_f64().map(SqlValue::Real))
            .unwrap_or(SqlValue::Null),
        Some(Value::String(s)) => SqlValue::Text(s.clone()),
        Some(other) => SqlValue::Text(other.to_string()),
    }
}

fn from_sql(v: SqlValue) -> Value {
    match v {
        SqlValue::Null => Value::Null,
        SqlValue::Integer(i) => json!(i),
        SqlValue::Real(f) => json!(f),
        SqlValue::Text(s) => json!(s),
        SqlValue::Blob(_) => Value::Null,
    }
}

fn write_items(conn: &mut Connection, items: &[Value]) -> rusqlite::Result<()> {
    let tx = conn.transaction()?;
    tx.execute("DELETE FROM logs", [])?;
    tx.execute("DELETE FROM things", [])?;
    {
        let mut ins_thing = tx.prepare(
            "INSERT INTO things(id,name,icon,cat,every,dueOn,deleted) VALUES(?,?,?,?,?,?,?)",
        )?;
        let mut ins_log = tx.prepare("INSERT INTO logs(id,thing_id,ts,note) VALUES(?,?,?,?)")?;
        for it in items {
            let id = py_str(&it["id"]);
            ins_thing.execute(params![
                id,
                py_str(&it["name"]),
                to_sql(it.get("icon")),
                to_sql(it.get("cat")),
                to_sql(it.get("every")),
                to_sql(it.get("dueOn")),
                to_sql(it.get("deleted")),
            ])?;
            if let Some(Value::Array(log)) = it.get("log") {
                for e in log {
                    let ts = e["ts"].as_f64().unwrap_or(0.0).trunc() as i64;
                    let note = match e.get("note") {
                        Some(v) if truthy(v) => py_str(v),
                        _ => String::new(),
                    };
                    ins_log.execute(params![py_str(&e["id"]), id, ts, note])?;
                }
            }
        }
    }
    tx.commit()
}

fn read_items(conn: &Connection) -> rusqlite::Result<Vec<Value>> {
    let mut things = conn.prepare("SELECT id,name,icon,cat,every,dueOn,deleted FROM things ORDER BY name")?;
    let mut logs = conn.prepare("SELECT id,ts,note FROM logs WHERE thing_id=? ORDER BY ts DESC")?;
    let rows = things.query_map([], |r| {
        Ok((
            r.get::<_, String>(0)?,
            r.get::<_, SqlValue>(1)?,
            r.get::<_, SqlValue>(2)?,
            r.get::<_, SqlValue>(3)?,
            r.get::<_, SqlValue>(4)?,
            r.get::<_, SqlValue>(5)?,
            r.get::<_, SqlValue>(6)?,
        ))
    })?;
    let mut items = Vec::new();
    for row in rows {
        let (id, name, icon, cat, every, due, deleted) = row?;
        let log: Vec<Value> = logs
            .query_map([&id], |r| {
                Ok(json!({
                    "id": from_sql(r.get::<_, SqlValue>(0)?),
                    "ts": from_sql(r.get::<_, SqlValue>(1)?),
                    "note": from_sql(r.get::<_, SqlValue>(2)?),
                }))
            })?
            .collect::<Result<_, _>>()?;
        items.push(json!({
            "id": id,
            "name": from_sql(name),
            "icon": from_sql(icon),
            "cat": from_sql(cat),
            "every": from_sql(every),
            "dueOn": from_sql(due),
            "deleted": from_sql(deleted),
            "log": log,
        }));
    }
    Ok(items)
}

/// Python truthiness, which server.py's validation relies on.
fn truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().map(|f| f != 0.0).unwrap_or(true),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

fn validate(items: &Value) -> bool {
    let Some(list) = items.as_array() else { return false };
    if list.len() > 5000 {
        return false;
    }
    for it in list {
        let Some(obj) = it.as_object() else { return false };
        if !obj.get("id").map(truthy).unwrap_or(false) || !obj.get("name").map(truthy).unwrap_or(false) {
            return false;
        }
        let log = match obj.get("log") {
            None => continue,
            Some(Value::Array(a)) => a,
            Some(_) => return false,
        };
        if log.len() > 100_000 {
            return false;
        }
        for e in log {
            let Some(eo) = e.as_object() else { return false };
            if !eo.get("id").map(truthy).unwrap_or(false) {
                return false;
            }
            if !matches!(eo.get("ts"), Some(Value::Number(_))) {
                return false;
            }
        }
    }
    true
}

// ---------------------------------------------------------------- http

fn allowed_origin(headers: &HeaderMap) -> Option<HeaderValue> {
    let origin = headers.get(header::ORIGIN)?;
    let s = origin.to_str().ok()?;
    CORS_ORIGINS.contains(&s).then(|| origin.clone())
}

fn json_response(status: StatusCode, payload: Value, headers: &HeaderMap) -> Response {
    let mut resp = (status, payload.to_string()).into_response();
    let h = resp.headers_mut();
    h.insert(header::CONTENT_TYPE, HeaderValue::from_static("application/json; charset=utf-8"));
    h.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    if let Some(origin) = allowed_origin(headers) {
        h.insert(header::ACCESS_CONTROL_ALLOW_ORIGIN, origin);
        h.insert(header::VARY, HeaderValue::from_static("Origin"));
    }
    resp
}

fn not_found() -> Response {
    let mut resp = (StatusCode::NOT_FOUND, "404 Not Found\n").into_response();
    resp.headers_mut().insert(header::CACHE_CONTROL, HeaderValue::from_static("no-cache"));
    resp
}

fn server_error(e: impl std::fmt::Display, headers: &HeaderMap) -> Response {
    eprintln!("error: {e}");
    json_response(StatusCode::INTERNAL_SERVER_ERROR, json!({"error": "server error"}), headers)
}

async fn handle(State(cfg): State<Shared>, method: Method, uri: Uri, headers: HeaderMap, body: Bytes) -> Response {
    let path = uri.path();
    match (method, path) {
        (Method::OPTIONS, "/api/items") => {
            let mut resp = StatusCode::NO_CONTENT.into_response();
            if let Some(origin) = allowed_origin(&headers) {
                let h = resp.headers_mut();
                h.insert(header::ACCESS_CONTROL_ALLOW_ORIGIN, origin);
                h.insert(header::ACCESS_CONTROL_ALLOW_METHODS, HeaderValue::from_static("GET, PUT, OPTIONS"));
                h.insert(header::ACCESS_CONTROL_ALLOW_HEADERS, HeaderValue::from_static("Content-Type"));
                h.insert(header::ACCESS_CONTROL_MAX_AGE, HeaderValue::from_static("86400"));
                h.insert(header::VARY, HeaderValue::from_static("Origin"));
            }
            resp
        }
        (Method::GET, "/api/items") | (Method::HEAD, "/api/items") => {
            let db = cfg.db_path.clone();
            let result = tokio::task::spawn_blocking(move || {
                let conn = connect(&db)?;
                read_items(&conn)
            })
            .await;
            match result {
                Ok(Ok(items)) => json_response(StatusCode::OK, json!({"items": items}), &headers),
                Ok(Err(e)) => server_error(e, &headers),
                Err(e) => server_error(e, &headers),
            }
        }
        (Method::PUT, "/api/items") => put_items(cfg, headers, body).await,
        (Method::GET, "/") | (Method::GET, "/index.html") | (Method::HEAD, "/") | (Method::HEAD, "/index.html") => {
            // Read on every request so a `git pull` ships the new page instantly.
            match tokio::fs::read(cfg.root.join("index.html")).await {
                Ok(bytes) => {
                    let mut resp = bytes.into_response();
                    let h = resp.headers_mut();
                    h.insert(header::CONTENT_TYPE, HeaderValue::from_static("text/html"));
                    h.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-cache"));
                    resp
                }
                Err(_) => not_found(),
            }
        }
        _ => not_found(),
    }
}

async fn put_items(cfg: Shared, headers: HeaderMap, body: Bytes) -> Response {
    let declared: usize = headers
        .get(header::CONTENT_LENGTH)
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.trim().parse().ok())
        .unwrap_or(0);
    if declared == 0 || declared > MAX_BODY || body.len() > MAX_BODY {
        return json_response(StatusCode::PAYLOAD_TOO_LARGE, json!({"error": "body too large or missing"}), &headers);
    }
    let items: Value = match std::str::from_utf8(&body).ok().and_then(|s| serde_json::from_str(s).ok()) {
        Some(v) => v,
        None => return json_response(StatusCode::BAD_REQUEST, json!({"error": "invalid JSON"}), &headers),
    };
    if !validate(&items) {
        return json_response(StatusCode::BAD_REQUEST, json!({"error": "invalid shape"}), &headers);
    }
    let db = cfg.db_path.clone();
    let result = tokio::task::spawn_blocking(move || -> rusqlite::Result<i64> {
        let mut conn = connect(&db)?;
        write_items(&mut conn, items.as_array().map(|a| a.as_slice()).unwrap_or(&[]))?;
        conn.query_row("SELECT COUNT(*) FROM logs", [], |r| r.get(0))
    })
    .await;
    match result {
        Ok(Ok(n)) => json_response(StatusCode::OK, json!({"ok": true, "logs": n}), &headers),
        Ok(Err(e)) => server_error(e, &headers),
        Err(e) => server_error(e, &headers),
    }
}
