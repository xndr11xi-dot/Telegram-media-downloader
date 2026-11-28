# Telegram Media Downloader

A privacy-focused desktop app to bulk download media from your Telegram channels and groups.

## Features

- 📢 Search and select channels or groups you are a member of
- Search forum topics and select one or more with checkboxes
- 🗂 Combine file type checkboxes — Photos, Videos, Audio, PDF, Word, Excel, ZIP, or any custom extension
- 🔢 Choose Last 10, 20, 50, 100, All, or a custom limit
- ⚡ Download 1–16 files at once with a remembered parallel-download setting
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
5. For forums, select one or more topics. Choose media type checkboxes and how many new files to download per topic (or per regular channel). With Include post discussions enabled, the limit counts channel messages and includes their matching comment media.
6. Click **Start**

## Saved preferences

The app automatically remembers your download folder, media selections, custom
extensions, file limit, parallel downloads, download order and date cutoff. Preferences are stored
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

## Parallel downloads

Choose **Parallel downloads** in Download settings. The default is **2** files at
once; choose **1** for sequential transfers or up to **16** for more overlap. The app
remembers the selection and locks it while a run is active. Parallelism is across
files, using the same Telegram connection and download quality. It does not split
one file into multiple downloads or create extra sessions.

The maximum is an application guard, not a published Telegram concurrency limit.
Higher values share the same bandwidth, CPU and destination drive and can lead
to more Telegram-requested waits. Compare the combined speed at different values
to choose a setting for your connection; a higher count does not ensure higher speed.

The queue selects files in the chosen order, but parallel files can finish in a
different order. Each topic retains its own limit. Pending transfers reserve file
limit slots so simultaneous completions cannot exceed a requested file count.
Discussion limits still count parent channel messages, and only those messages'
discussions are read. Existing and already queued files are skipped. The previous
one-second wait after every successful file has been removed.

Activity shows the latest file's bytes, progress and ETA plus the number of active
files and their combined average speed. These are file-level estimates, not an ETA
for the whole channel. Pause applies to all transfers; Cancel stops active transfers
and removes their partial files. Sync advances only after the relevant history
scan and transfers succeed. Completed discussions can save their own checkpoint
while another discussion is still downloading or has failed.

Telegram-requested waits reported by file transfers pause new starts and retries
for the requested duration; Activity reports Waiting for Telegram. Cancel also
interrupts these waits. Retryable errors retain the existing five-attempt limit.

When storage is full (`ENOSPC`, errno 28 on macOS) or a storage quota is exhausted,
the run stops immediately instead of retrying the same files. Other parallel
transfers and outstanding discussion reads are cancelled, and remaining topics
are not started. Activity displays a storage-specific message and clears speed.
Completed files remain in place; unfinished scans retain their previous sync
positions. Partial files are removed when the filesystem permits, with a warning
if cleanup is blocked. Free space on the drive selected in Download folder, then
retry the same scope. A sync reset is not required to recover the missing files.

Speed depends on file sizes, connection, disk/CPU and Telegram's limits, so more
parallel files do not guarantee faster downloads. See the
[Telethon FAQ](https://docs.telethon.dev/en/stable/quick-references/faq.html#file-download-is-slow-or-sending-files-takes-too-long)
for Telegram download performance considerations.

## Private issue diagnostics

The Activity Log remains an on-screen record for the current run. Separate private
diagnostics are now started by `main.py` and persist errors across app restarts.
Open **Activity → Log → Open diagnostics** to reveal the log folder in Finder
(or the platform's file manager).

The files live under `.telegram-downloader/diagnostics/`, which is ignored by Git.
`issues.log` rotates at 256 KiB, keeping three backups (`issues.log.1` through
`.3`), for about 1 MiB total. Directories use mode 700 and files mode 600 on macOS.
No new dependencies, uploads, analytics or external issue reports are added.

Diagnostics cover handled login/topic/sender/download/storage failures, transfer
retries and Telegram waits, plus unhandled Python, GUI callback, background-thread
and asynchronous-task errors. They contain UTC timestamps, fixed event codes,
error types, application source filenames/line numbers, Python/library versions,
generic OS name and limited operational counts. They omit raw exception messages,
traceback source text/locals, full filesystem paths, credentials, phone numbers,
OTPs, session contents, account/channel/sender/message IDs, titles and media names.
Activity text and download history are not copied into these files.

A small private per-run marker tracks whether the window closed normally. The
next launch checks for leftover markers from processes no longer running and
records a notice. Force Quit, shutdown and native crashes can all cause this notice;
it is evidence of an interrupted run, not proof of a particular bug. Forced exits
cannot always execute Python error handlers, so the exact cause may be unavailable.
Live markers from another running instance are left alone. Closing the window
during an active download is recorded separately as an intentional close.

If diagnostic storage cannot be opened, the app continues and displays a local
permissions notice. Logging failures do not expose raw exception contents or
prevent ordinary app use. No diagnostics are initialized merely by importing
modules for tests or other tools.

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

## Channel post discussions

Select a broadcast channel and enable **Include post discussions** in Download
settings. This remembered option is off by default. It also downloads matching
media from the comments on accessible channel posts, including nested replies
and comments under text-only posts. It never joins a group automatically or
downloads unrelated messages from the linked group. For ordinary groups and
forum topics, replies are already part of their selected history.

Comment media goes inside the channel folder under
`discussions/group_<id>/thread_<id>/`. Channel posts and discussion groups use
different message IDs, so their files and checkpoints stay separate. Album posts
sharing a discussion reuse one thread folder. Filenames use each comment's own
message date. Media types and sender filters apply to the comment itself,
including text-only parents or parents from a different sender. Date restrictions
bound the parent-message window and also filter each comment by its own date.

With discussions enabled, the limit counts **channel messages**, including those
without matching media. For example, **Last 10** with newest-first order processes
the latest ten channel messages and all matching comment media from those messages.
Comment files do not use up the message limit. Existing or filtered-out files do
not extend the window to older posts. Oldest-first order uses the first N messages
in that direction. A date restriction starts the window at that date boundary.
Without discussions, limits retain their usual meaning: the number of new files.

**All new messages** uses the saved channel position and processes discussions
only on channel messages included in that run. It does not recheck older posts for
new replies. To revisit recent discussions, choose a numbered window; to rescan
the whole history, use Reset saved sync and All with no date cutoff. Completed All
scans retain independent discussion checkpoints for each filter, sender and
destination. Numbered or date-restricted runs do not advance unrestricted sync.
Existing files are skipped in every mode.

Posts and their discussions are queued in the selected order; parallel file
transfers can finish in a different order. Comments across all threads are not
globally sorted by date. Activity
reports discussion access failures and retains unfinished sync positions for retry.

## Rescan history and recover missing files

Select a channel or group, then click Reset saved sync at the bottom of the
Channels panel. The confirmation identifies the selected source. This clears
its saved sync positions across all topics, discussions, senders, media filters and destination
folders. Other sources keep their saved positions. Reset is available while idle.

After resetting, choose All, clear the optional date and click Start to rescan
history using the current topic, sender and media selections. Files still present
in the destination are skipped, and missing matching files are downloaded again.
A completed run establishes a new checkpoint. Activity history remains a separate
record of previous runs.

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
