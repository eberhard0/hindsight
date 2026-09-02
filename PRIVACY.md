# Hindsight — Privacy Policy

_Last updated: 2 September 2026_

Hindsight is a personal "when did I last do that?" tracker. This policy covers the Android app published on Google Play and the open-source code at <https://github.com/eberhard0/hindsight>.

## What the app stores

Everything you type into Hindsight — the names of the things you track, when you logged them, optional notes, categories, and reminder settings — is stored **only on your device**, in the app's private storage. Nothing is sent anywhere by default.

## Optional sync to your own server

Hindsight can optionally sync with a server that **you** run (the same open-source `server.py` from the repository). Sync is off until you enter a server address under **Sync server** in the app. When enabled, your tracked items are sent to and fetched from that address over the network. You control that server, so you control that data; the app developer never receives it.

## What the app does not do

- No account, no sign-in.
- No analytics, advertising, crash reporting, or tracking SDKs of any kind.
- No data is sent to the developer or to any third party.
- No access to contacts, location, camera, microphone, or files other than a CSV you explicitly choose to import or export.

## Permissions

- **Notifications** — only to show the reminders you set. You can decline the permission; the app works without it.
- **Exact alarms** — used so a reminder fires on the day it is due.
- **Internet** — used only when you turn on sync to your own server.

## Data deletion

Uninstalling the app deletes all of its data from your device. If you enabled sync, the copy on your server is yours to delete there.

## Children

Hindsight is not directed at children under 13 and collects no personal information from anyone.

## Changes

If this policy changes, the updated version will be published at the same address with a new date.

## Contact

Questions: open an issue at <https://github.com/eberhard0/hindsight/issues>.
