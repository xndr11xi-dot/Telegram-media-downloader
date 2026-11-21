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

## Saved preferences

The app automatically remembers your download folder, media selections, custom
extensions, file limit, download order and date cutoff. Preferences are stored
privately in the ignored preferences.local.json file beside the application.
Connection details are saved separately when Remember connection details on this
Mac is checked. After a successful login, the API ID, API hash and phone number
are stored as plaintext in .telegram-downloader/credentials.json, with owner-only
file permissions (600) inside a private directory (700). This directory is
excluded from Git. The fields are filled on the next launch; click Log in to
connect. Telegram codes are never saved. Forget saved details removes the file,
clears the fields and disables remembering. Unchecking Remember also removes
previously saved details. Channel and topic selections are chosen after login.

Use Calendar beside the date field to select a day, navigate months, choose
Today or clear the cutoff. The field also accepts YYYY-MM-DD directly. Calendar
dates and the Today shortcut use UTC, matching message-date filtering.

## Download from a message date

Enter an optional date (YYYY-MM-DD, UTC) under Download order. Oldest → Newest
includes messages on or after that date. Newest → Oldest includes messages on
or before it. The entire cutoff day is included in both directions. Leave the
date blank for the usual download behavior. Date-filtered runs use the same
media filters and per-topic limits, and bypass the normal sync checkpoint so
you can revisit older dates.

## Library layout

The wider channel sidebar has a typable dropdown. Open its arrow to browse full
channel names and IDs without typing, or type a title or ID to filter and press
Return to select the first match. The sidebar rows also remain clickable. After
selection, the dropdown restores the full list for browsing the next channel.

The narrower topics column has a typable dropdown and checkboxes. Selecting an
item from the dropdown adds it to the checked topics, then restores the full list.
Use checkboxes to deselect individual topics or Clear to remove all selections.
Typing filters both the dropdown and the checkbox list while preserving hidden
selections. IDs distinguish duplicate titles. Click a group again to retry topic
loading.

Media filters, the file limit and download folder are on the right. Expand
Dates, order & custom types for the calendar, download order and custom extensions.
The current date and order remain visible in the settings summary. Preferences
restore automatically, including settings in the collapsed section.

Drag the vertical dividers to set the width of each section. Widths and window
size are saved automatically and restored on the next launch. Each section has
a minimum width to keep controls accessible. Reset layout restores balanced
section widths. At 1160 pixels or wider all three columns are visible. Medium windows keep the
sidebar and switch between Topics and Settings. Below 880 pixels, the Channels,
Topics and Settings switch shows one panel at a time. Resizing preserves inputs.
The app follows the system's light or dark appearance.

Login collapses after your channels load and can be reopened with Show login.
Activity opens Transfer, Log and History tabs above the footer. Transfer opens
automatically when a download starts and shows the current source and file,
received/total bytes, file percentage, average transfer speed and estimated time
remaining for that file. A compact summary stays in the footer when Activity is
closed. Downloaded/skipped counts cover all selected topics. Unknown file sizes
show size unknown and no ETA. Speed is averaged over the current attempt,
excluding paused time, and resets on retry. All mode scans without a known file
total, so the main progress bar remains animated during scanning. Progress and the
Start / Pause / Cancel controls stay available at the bottom.

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
are saved under a sanitized topic name plus its ID, such as `Photography_12345`,
inside the group folder. History records the topic.
Existing `topic_<id>` folders are renamed on the next download and their sync
checkpoints migrate with them. Files are retained. Later topic-title changes
reuse the existing folder by ID. If multiple folders already share a topic ID,
the app reports a conflict so you can review them before downloading.
Ordinary channels and groups keep their existing behavior.

Topic matching uses Telegram's `forum_topic`, `reply_to_top_id`, and
`reply_to_msg_id` fields. General (ID 1) includes messages without a forum reply
header. Named topics are fetched directly through their reply thread; General uses
group history. Local topic filtering runs before media type and file limits. It never falls back to a
whole-group download when topic loading fails.

Topic sync checkpoints are independent of whole-group checkpoints and of other
topics and media filters. Only a completed All scan advances the checkpoint;
cancelled or failed scans can be retried without skipping unfinished files.

## Download from a specific sender

In Download settings, use the sender field and Find. Enter an @username, a numeric
Telegram sender ID, or a name to search the selected group's members. For multiple
matches, select the intended sender from the dropdown; IDs distinguish duplicate
names. Numeric IDs can be used directly without loading a sender profile.

Only selected sender combines with the chosen topics, media types, file limit,
date and download order. Uncheck it to include Everyone. Sender choices reset
when changing channels/groups. Sender-filtered incremental checkpoints are
independent from Everyone and from other senders; existing matching files in the
same destination are still skipped.

Member-name search depends on Telegram's permissions and may be unavailable.
Username and numeric-ID input provide other ways to choose a sender. Filtering
uses the sender identity attached to the message. Forwards match the account that
posted the forward, and anonymous/channel posts expose their group/channel
identity rather than a hidden person's account. The first run for a new sender
may scan the selected history before subsequent runs resume incrementally.

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

Downloads use stable `<message-id>_<YYYY-MM-DD>.<extension>` filenames, private temporary
files and atomic replacement; interrupted transfers are removed. Group folders
include a sanitized title and group ID, preventing path traversal and same-title
collisions. Existing `<message-id>.<extension>` files in the same folder still count as
already downloaded. New filenames use the Telegram message date in UTC.

Checkpoints include group, topic, media filter and destination. Old checkpoints
are deliberately ignored to avoid carrying forward potentially incomplete scans.
A completed All scan advances sync; failure or cancellation leaves it unchanged.
State/history writes use private files and atomic replacement. Pause and cancel are honored at Telegram's transfer progress callbacks and
between requests/retries. An in-flight request may finish before cancellation
removes its temporary file.

This distribution contains the runtime application and its dependencies. Development
tests, audit tools and review documents are maintained separately and are not
required to run the app. Python 3.11.9, CustomTkinter 5.2.2 and Telethon 1.40/1.45
were used for automated validation; live macOS layout and account checks remain
manual.
