# Telegram Media Downloader

A privacy-focused desktop app to bulk download media from your Telegram channels and groups.

## Features

- 📢 Search and select channels or groups you are a member of
- Search forum topics and select one or more with checkboxes
- 🗂 Combine file type checkboxes — Photos, Videos, Audio, PDF, Word, Excel, ZIP, or any custom extension
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
git clone https://github.com/xndr11xi-dot/Telegram-media-downloader.git
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
4. Search and select a channel or group in the left panel
5. For forums, select one or more topics. Choose media type checkboxes and how many new files to download per topic (or per regular channel).
6. Click **Start**

## Desktop layout

Wide windows show channels and topics on the left and download settings on the
right. The topic list grows with the window; settings scroll independently when
needed. Below 1040 pixels wide, use the Channels & topics / Download settings
switch to move between panels. Your selections stay in place when resizing.

Use Hide login after signing in to free space. Activity has Log and History tabs
and can also be hidden. On shorter screens it starts collapsed; choose Show
activity to open it. Progress and Start / Pause / Cancel stay visible at the
bottom of the window.

## Privacy

- All data stays on your machine
- Session files stored locally only
- No analytics, no telemetry, no ads

## Disclaimer

This tool uses the official Telegram API and only works with channels and groups you are already a member of. Use responsibly and in accordance with Telegram's Terms of Service.

## License

MIT License


## Forum topics

For forum-enabled supergroups, choose one or more topics after selecting the group. Topic
names include their IDs so duplicate titles remain distinguishable. Downloads
are saved under `topic_<id>` inside the group folder and history records the topic.
Ordinary channels and groups keep their existing behavior.

Topic matching uses Telegram's `forum_topic`, `reply_to_top_id`, and
`reply_to_msg_id` fields. General (ID 1) includes messages without a forum reply
header. Named topics are fetched directly through their reply thread; General uses
group history. Local topic filtering runs before media type and file limits. It never falls back to a
whole-group download when topic loading fails.

Topic sync checkpoints are independent of whole-group checkpoints and of other
topics and media filters. Only a completed All scan advances the checkpoint;
cancelled or failed scans can be retried without skipping unfinished files.

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

This distribution contains the runtime application and its dependencies. Development
tests, audit tools and review documents are maintained separately and are not
required to run the app. Python 3.11.9, CustomTkinter 5.2.2 and Telethon 1.40/1.45
were used for automated validation; live macOS layout and account checks remain
manual.
