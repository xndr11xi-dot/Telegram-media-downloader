# Topic downloader security and test review

Review date: 2026-11-08 (America/Mexico_City).

## Git and sensitive data

Fetched the public fork and inspected all reachable history from main, custom,
and feature/topic-specific-downloads: 8 commits, 15 unique historical blobs.
The original Git index held 9 source/documentation files. No session, media,
local configuration, history or sync-state files were tracked. Pattern and
hardcoded-value checks found no real credentials. Historical phone-pattern hits
were the app's public example placeholder; no value is reproduced here.
The proposed index and new commit are scanned again before publication.

No real Telegram session was opened and no real credential was used during this
review. Test sessions are empty temporary files with TelegramClient mocked.
Automated downloads write only synthetic fixture bytes to temporary directories.
No real credential or session content was printed, committed or attached.

The repository audit reports only finding categories and Git object IDs. This
heuristic review does not cover deleted/unreachable remote objects, hidden forks,
external backups or every possible secret encoding. If a real secret is later
found, stop and revoke/rotate it before further publishing or history cleanup.

## Findings addressed

- Extend ignore rules for SQLite session sidecars, environments, local configs,
  state/history, credentials, media, generated download folders, caches and venvs.
- Remove raw login/discovery/download exception text from logs. Mask hash,
  phone and OTP fields; clear submitted OTPs and login fields. Release the OTP
  future after authentication. Real credentials never enter test fixtures.
- Store new sessions under an ignored private directory, with phone-free account
  filenames and private file permissions. Reject session-directory/file symlinks.
- Replace ambiguous numeric-prefix duplicate checks with exact, deterministic
  message filenames. Prevent remote titles/filenames from supplying path traversal.
- Download to private temporary streams, atomically publish only successful
  transfers and remove failed/cancelled partial files. Reject destination symlinks.
- Scope sync by group/topic/filter/destination, normalize filter sets, ignore
  legacy checkpoints, and write private JSON state/history atomically. Corrupt
  JSON causes a safe rescan rather than skipping messages.
- Do not advance sync after failed/cancelled/incomplete scans. Retry transient
  failures without logging their contents. Respect cancellation during pause,
  retries and transfer completion, including immediately after scheduling a job.
- Fix Telethon 1.45's moved topic-discovery API while retaining 1.40 compatibility.
- Keep topic-loading failures disabled; discard stale responses after group switches.

## Executed validation

| Check | Result |
| --- | --- |
| Mocked suite on Intel macOS, Python 3.11.9, Telethon 1.40.0 | 37 passed |
| Same suite with Telethon 1.45.0 and CustomTkinter 5.2.2 | 37 passed |
| Python compilation and Python 3.8 syntax parsing | Passed; 3.8 runtime not tested |
| History and proposed Git index heuristic audit | No findings |
| Ignore rules for representative sensitive/local artifacts | Passed |
| Resolved application requirements vulnerability audit | No known vulnerabilities reported |
| Isolated test environment vulnerability audit after tooling updates | No known vulnerabilities reported |
| GUI module/Tk 8.6 imports on Intel macOS | Passed |
| Visible GUI launch | Blocked: native process aborted (exit 134) in automation session |
| Live Telegram login/downloads | Not run: no real account credentials used |
| Packaging and other Python/OS versions | Not run |

The mocked suite covers paginated/empty/failed/nonadvancing topic discovery,
General/direct/nested topic membership, duplicate titles, channel selection,
media filters before limits, ordinary channels, exact duplicate detection,
incremental reruns and both orders, scope isolation, pause/resume, cancellation
before scheduling/while paused/during retries/during transfer, retry exhaustion,
transient failures, missing media, iterator failures, safe paths, private session
permissions, symlink rejection, atomic state failure, corrupt state recovery,
GUI error recovery, stale topic responses, and OTP/log privacy.

The fresh venv initially inherited vulnerable pip/setuptools tooling. They were
updated only inside the ignored test environment, then re-audited. No application
runtime dependency vulnerability was reported. Vulnerability databases and
resolutions change, so repeat the audit before release.

## Remaining manual checks and limitations

Before approving a merge, use a local account to verify General and two named
forum topics, ordinary channels, limits and media filters, pause/cancel/rerun in
both orders, and the visible layout. Check that error/cancel status stays accurate
and no sensitive content appears in logs. Never attach credentials or sessions.

Named topics now request their reply thread directly; General retains group
history with local filtering. Controls act between API requests and do not abort an in-flight
network request. Closed/hidden topics returned by Telegram remain selectable;
deleted/missing topics fail closed. No password/2FA prompt was added: accounts
requiring additional authentication receive a generic login failure.

Old session paths, download filenames/folders and sync checkpoints are not
migrated. Reauthentication and a safe rescan/redownload may be required. Generated
files remain local. Ignore rules are not a substitute for reviewing the index.
Local filesystem attackers with access to the selected download directory,
remote edits/deletions to older Telegram messages, and concurrent app processes
sharing state are outside this change's guarantees. Use one instance per state
location. No claim of complete vulnerability absence is made.

All changes remain on a feature branch. No merge is authorized by this review.


## Download-start follow-up (2026-11-08)

The prior implementation scanned the entire group before finding a selected
named topic. It now requests that topic through Telethon's `reply_to` argument,
uses the discovered entity directly, and retains defensive local filtering.
General and ordinary channels continue using unthreaded history. A fixed,
non-resizable 960-pixel window also made lower controls inaccessible on smaller
screens; the form is now scrollable in a screen-height-aware, resizable window.
An immediate start log distinguishes a button click from later network work.
These are code-level defects; the user's specific live failure is not reproduced
with their account and remains subject to the GUI retest.

40 mock-based tests pass with the installed Telethon 1.45.0. Added coverage checks
thread request routing, General/ordinary history routing, selected-topic download
start, duplicate-click suppression, successful completion and control recovery.
No live account credentials or session were used. See MANUAL_RETEST.md for the
GUI-only retest sequence. No merge was performed.
