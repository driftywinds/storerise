# storerise
A Telegram bot to monitor apps on the App Store (and MiXplorer) and send notifications with Apprise

## Following apps

| Command | What it does |
|---|---|
| `/add <app id, bundle id or App Store URL>` | Follow an App Store app |
| `/add mixplorer` | Follow MiXplorer (Android), checked against the developer's update manifest |
| `/check` | Poll right now and reply with the latest version of everything you follow (new releases still notify as usual) |
| `/list`, `/remove`, `/status` | Manage what you follow |
| `/apprise ...` | Add extra notification channels (Discord, email, Slack, ...) |

Everything is checked once an hour. A new release is sent to Telegram and to every Apprise endpoint you have enabled.

## MiXplorer

MiXplorer is not on the App Store, so it is read from the developer's update manifest instead. A release is detected when either the version or the build number changes (e.g. `6.71.15 (B26090420)`), and the notification links to the developer's Google Drive folder.

The manifest URL can be overridden with the optional `MIXPLORER_URL` environment variable.
