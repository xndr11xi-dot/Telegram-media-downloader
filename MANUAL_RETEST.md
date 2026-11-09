# macOS GUI retest

Use GitHub Desktop to select `xndr11xi-dot/Telegram-media-downloader`, click
Fetch origin, and choose `fix/topic-download-start` in Current Branch. Pull if
offered. Use Repository → Open in Visual Studio Code. Select your existing
Python environment using Command-Shift-P → Python: Select Interpreter. Open
`main.py` and click Run Python File (the play button). Close older app instances.

1. Confirm the window fits the screen. Scroll the right-hand scrollbar to reach
   Save To, Start, progress, and Log. Resize the window and confirm access remains.
2. Log in locally. Choose a forum and wait until topics load. Choose a named topic
   with a known small photo or document. Selecting a topic alone does not start a
   download: the Start button must be clicked.
3. Set File Type Filter to All. Under How Many Files select Custom and enter 1.
   Choose Newest → Oldest. Browse to a NEW empty folder under Downloads, outside
   the repository. Click Start.
4. Expect the log to show “Starting download for the selected channel/topic...”,
   then scanning/order messages, then one successful file and “Download complete”.
   Start should become available again. In Finder open the selected folder, then
   the group-and-ID folder, then `topic_<selected ID>`. Open the file and verify
   it belongs to the chosen topic. A large file can take time before progress
   updates; use a small known file for this first check.
5. Select a second named topic and repeat with Custom 1. Its file must be in a
   separate `topic_<ID>` folder and belong only to that topic. Test General too.
6. Select PDF (on a topic containing a PDF), Custom 1, and repeat in a fresh base
   folder. Confirm exactly one PDF and no photos/videos. Repeat All with the
   opposite download order. A topic without matching media can correctly return 0.
7. Choose an ordinary channel. Confirm “No topic required”, then repeat All,
   Custom 1 in a fresh base folder. Confirm a file downloads without a topic folder.
8. On a small test topic choose How Many Files → All. Complete a run, then click
   Start again with identical topic/filter/folder. Expect no duplicate files.
   After a new file is posted, rerun and confirm only that new file downloads.
9. On a topic with several files choose All. Pause, wait for the active request
   to finish, verify no further files start, then Resume. Cancel another run;
   expect Download cancelled and Start re-enabled. Rerun and verify unfinished
   files download. Pause/Cancel take effect between requests, not mid-transfer.
10. In GitHub Desktop inspect Changes after testing. Session files,
    `.telegram-downloader`, history/sync JSON, local configuration, and downloaded
    media must not appear. Do not force-add ignored files. Keep downloaded files
    outside the checkout and do not attach credentials/session files to the PR.

If step 3 fails, report whether Start was visible/enabled, whether its immediate
start log appeared, the final status, the chosen filter/limit/order, and whether
the topic contains a matching file. Share only redacted log text; omit account,
group, topic and local path details. Live account behavior and visible layout
remain manual checks; the automated tests use mocks and temporary synthetic files.
