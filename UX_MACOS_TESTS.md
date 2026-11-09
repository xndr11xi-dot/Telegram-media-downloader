# Search and multi-select UX: macOS review

Base: `fix/topic-download-start`. Feature: `feature/searchable-multi-select-ux`.

## Get and launch (GitHub Desktop + VS Code)

1. In GitHub Desktop select this repository, Fetch origin, choose the feature branch, and Pull if offered.
2. Choose Repository → Open in Visual Studio Code. Use Command-Shift-P → Python: Select Interpreter and choose the environment used for your working version (requirements.txt remains unchanged).
3. Open main.py and click Run Python File. Log in with your own credentials locally.

## Selection and layout

1. Resize the window wide and narrow (minimum 620×540); scroll settings. Start, Pause, Cancel and progress should remain visible below the settings.
2. Type part of a channel/group name. Open the selector to see matching names, or press Return to choose the first match. IDs distinguish duplicate titles. A query with no matches should say zero matches and retain the previous selection; clear the search to restore the list.
3. Select a forum group. While topics load, Start stays disabled. On failure, reselect the group to retry. Start stays disabled when no topics are available.
4. Select two topics, search for another title, and confirm the selected count still includes hidden selections. Select visible selects only matches; Clear selection clears every topic. Duplicate topic names display their IDs.
5. Switch groups while topics are loading; results for the previous group must not replace the new group's topics. A regular channel should show No topic required.

## Small download checks

1. Choose a new empty destination with Browse. Select two topics with known photos, videos and PDFs. Check Photos + Videos, leave All media unchecked, set Custom number to 2. The limit applies independently to each topic and counts newly downloaded files.
2. Start. Only photos and videos from those two topics should appear, under separate topic_ID folders within the group folder. Check the log's scope numbers. During All mode the progress indicator animates while scanning; limited mode shows per-topic progress. Completion reports complete, incomplete, cancelled or failed.
3. Repeat to confirm existing files are skipped. Select All for the file limit to establish incremental sync, then repeat; change selected topics and media types to confirm each scope resumes independently. Add PDF or Custom extensions `.pdf,.csv` and confirm these are combined with checked types. All media explicitly overrides selected types.
4. Pause, resume, then cancel during the first topic of a multi-topic job. Remaining topics should not start. Start must become available again. Cancelled/incomplete topics must not advance their sync checkpoint.
5. Repeat Photos + Videos with a regular channel. No topic selection should be needed and ordinary channel downloads should still work.
6. Clear every media checkbox with All media unchecked, enter an invalid custom limit, and clear the destination in separate attempts. Start should explain the missing input in the log without launching a job.
7. Relaunch and confirm history remains local. GitHub Desktop Changes must contain no credentials, sessions, state, history, logs or downloaded files.

## Automated validation

Run `python -m unittest discover -s tests -q` in the configured environment. Tests use synthetic Telegram messages and temporary destinations; no login is needed. Run `python tools/audit_repository.py` for the index/history audit.

Native visual validation remains a manual check: the automated environment could import CustomTkinter 5.2.2 and run controller tests, but its native Tk launch exited before rendering.
