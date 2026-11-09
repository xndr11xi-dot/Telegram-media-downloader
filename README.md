# Telegram Media Downloader

A privacy-focused desktop app to bulk download media from your Telegram channels and groups.

## Features

- 📢 Select any channel or group you're a member of
- 🗂 Filter by file type — Photos, Videos, Audio, PDF, Word, Excel, ZIP, or any custom extension
- 🔢 Control how many files — Last 20, 50, 100, All, or custom number
- 📅 Choose download order — Newest first or Oldest first
- 📁 Browse and select your download folder
- ⏸ Pause, resume, and cancel downloads anytime
- 🔄 Incremental sync — resumes from where you left off
- 📋 Download history log
- 💻 100% local — no server, no cloud, no third party
- 🔒 Direct connection to Telegram's official API

## Requirements

- Python 3.8+
- A Telegram account
- API credentials from [my.telegram.org](https://my.telegram.org/apps)

## Installation

```bash
git clone https://github.com/randaft20-cloud/Telegram-media-downloader.git
cd Telegram-media-downloader
pip install -r requirements.txt
python main.py
```

## Getting API Credentials

1. Go to [my.telegram.org](https://my.telegram.org/apps)
2. Log in with your phone number
3. Click **Create Application**
4. Copy your `api_id` and `api_hash`

## Usage

1. Run the app
2. Enter your API ID, API Hash and phone number
3. Click **Login** — enter the OTP sent to your Telegram app
4. Select a channel or group from the dropdown
5. Choose file type and how many files to download
6. Click **Start**

## Build as .exe (Windows)

```bash
pyinstaller --onefile --windowed --name="TelegramDownloader" main.py
```

Find your `.exe` in the `dist/` folder.

## Privacy

- All data stays on your machine
- Session files stored locally only
- No analytics, no telemetry, no ads

## Disclaimer

This tool uses the official Telegram API and only works with channels and groups you are already a member of. Use responsibly and in accordance with Telegram's Terms of Service.

## License

MIT License


## Forum topics

For forum-enabled supergroups, choose a topic after selecting the group. Topic
names include their IDs so duplicate titles remain distinguishable. Downloads
are saved under `topic_<id>` inside the group folder and history records the topic.
Ordinary channels and groups keep their existing behavior.

Topic matching uses Telegram's `forum_topic`, `reply_to_top_id`, and
`reply_to_msg_id` fields. General (ID 1) includes messages without a forum reply
header. The app scans group history and filters before applying media type and
file limits; large forums may take longer to scan. It never falls back to a
whole-group download when topic loading fails.

Topic sync checkpoints are independent of whole-group checkpoints and of other
topics and media filters. Only a completed All scan advances the checkpoint;
cancelled or failed scans can be retried without skipping unfinished files.

Run automated tests with `python -m unittest discover -s tests -v`.
For a live check, select a forum with General and two named topics, download each,
verify the separate folders contain only the selected topic's media, then cancel
and rerun All in both orders. Also verify an ordinary channel, and switch groups
while topics are loading. Live checks require your own Telegram login.

## Security and compatibility

Keep all credentials, OTPs, passwords, sessions, media, configuration and local
state out of Git. `.gitignore` covers these common artifacts; it cannot protect
files forcibly added to Git or arbitrary personal files. Never paste credentials
or session contents into issues, logs, screenshots or test fixtures.

New sessions live in the ignored `.telegram-downloader/` directory, with hashed
account filenames (no plain phone numbers), directory mode 700 and session mode
600 on macOS. Old `session_*.session` files are not automatically imported: sign
in again, and manage/revoke obsolete sessions from Telegram. Never upload them.
API hashes, phone numbers and OTPs are masked; submitted OTPs and completed login
fields are cleared. Raw exception messages are omitted from application logs.

Downloads now use stable `<message-id>.<extension>` filenames, private temporary
files and atomic replacement; interrupted transfers are removed. Group folders
include a sanitized title and group ID, preventing path traversal and same-title
collisions. Existing downloads under the older naming scheme are not migrated
or recognized as completed files. The first run can therefore redownload them.

Checkpoints include group, topic, media filter and destination. Old checkpoints
are deliberately ignored to avoid carrying forward potentially incomplete scans.
A completed All scan advances sync; failure or cancellation leaves it unchanged.
State/history writes use private files and atomic replacement. Pause and cancel
are honored between requests/retries; an in-flight Telegram request finishes
before its temporary file is discarded on cancellation. These controls do not
interrupt an active network transfer.

The automated suite uses only mocked Telegram responses and synthetic fixtures:

```bash
python -m unittest discover -s tests -v
python tools/audit_repository.py
```

The audit scans all reachable Git history and the index, reporting object IDs
and finding categories without contents. It is a heuristic check, not proof
that no secret exists. If any real secret or session is found, stop publication
and revoke/rotate it before continuing; deleting the current file is insufficient.

Tested on Intel macOS (`x86_64`) with Python 3.11.9, CustomTkinter 5.2.2 and both
Telethon 1.40.0 and 1.45.0. Both forum-discovery API layouts are supported.
Python 3.8 syntax was checked, but other Python runtimes were not exercised.
Tk 8.6 imports succeeded; the graphical launch aborted in the automation session,
so visible layout and live account behavior still need manual verification.
See `SECURITY_REVIEW.md` for the audit scope, results and remaining checks.
