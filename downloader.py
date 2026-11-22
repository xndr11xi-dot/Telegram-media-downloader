from telethon import TelegramClient, utils
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import GetDiscussionMessageRequest
try:
    # Telethon 1.45 / Telegram layer 214 moved forum discovery to messages.
    from telethon.tl.functions.messages import GetForumTopicsRequest
    TOPIC_PEER_ARGUMENT = "peer"
except ImportError:
    from telethon.tl.functions.channels import GetForumTopicsRequest
    TOPIC_PEER_ARGUMENT = "channel"
from telethon.tl.types import (
    MessageMediaPhoto,
    MessageMediaDocument,
    DocumentAttributeFilename,
    User, Channel, PeerChannel,
)
import asyncio
import os
import json
import hashlib
import re
import tempfile
import time
from datetime import datetime, timedelta, timezone
from local_data import read_json, write_json

# ── Incremental sync ──
SYNC_FILE = "sync_state.json"


class TopicFolderConflict(FileExistsError):
    pass

def sync_key(channel_id, topic_id=None, media_filter=None, folder=None, sender_id=None, discussion=None):
    filters = sorted(set(x.strip().lower() for x in (media_filter or "all").split(",")))
    scope = f"{channel_id}:topic:{topic_id}:filter:{','.join(filters)}"
    if sender_id is not None:
        scope += f":sender:{sender_id}"
    if discussion is not None:
        group_id, root_id = discussion
        scope += f":discussion:{group_id}:thread:{root_id}"
    if folder is not None:
        destination = os.path.normcase(os.path.realpath(folder))
        scope += ":destination:" + hashlib.sha256(os.fsencode(destination)).hexdigest()
    return scope


def message_in_topic(message, topic_id):
    if topic_id is None:
        return True
    reply = getattr(message, "reply_to", None)
    if reply and getattr(reply, "forum_topic", False):
        root = getattr(reply, "reply_to_top_id", None) or reply.reply_to_msg_id
        return root == topic_id
    return topic_id == 1


def load_last_id(channel_id, topic_id=None, media_filter=None, folder=None, sender_id=None, discussion=None):
    data = read_json(SYNC_FILE, {})
    value = data.get(sync_key(channel_id, topic_id, media_filter, folder, sender_id, discussion), 0)
    return value if type(value) is int and value >= 0 else 0


def save_last_id(channel_id, message_id, topic_id=None, media_filter=None, folder=None, sender_id=None, discussion=None):
    data = read_json(SYNC_FILE, {})
    key = sync_key(channel_id, topic_id, media_filter, folder, sender_id, discussion)
    previous = data.get(key, 0)
    data[key] = max(previous if type(previous) is int else 0, message_id)
    write_json(SYNC_FILE, data)


def reset_channel_sync(channel_id):
    """Clear checkpoints for one source, across all topics, filters and folders."""
    if type(channel_id) is not int or channel_id == 0:
        raise ValueError("Select a valid channel or group")
    data = read_json(SYNC_FILE, {})
    prefix = f"{channel_id}:"
    remaining = {key: value for key, value in data.items()
                 if key != str(channel_id) and not key.startswith(prefix)}
    removed = len(data) - len(remaining)
    if removed:
        write_json(SYNC_FILE, remaining)
    return removed


def group_folder(base, name, channel_id):
    # Telegram titles cannot introduce path components or parent traversal.
    component = re.sub(r"[^\w .-]", "_", name).strip(" .")[:80] or "group"
    return os.path.join(base, f"{component}_{channel_id}")


def discussion_folder(base, group_id, root_id):
    for identifier in (group_id, root_id):
        if type(identifier) is not int or identifier < 1:
            raise ValueError("Invalid discussion identity")
    for component in ("discussions", f"group_{group_id}", f"thread_{root_id}"):
        base = os.path.join(base, component)
        if os.path.islink(base):
            raise ValueError("Discussion folders must not be symbolic links")
        os.makedirs(base, exist_ok=True)
    return base


def topic_folder(base, title, channel_id, topic_id):
    """Reuse folders by topic ID, migrating legacy names and their checkpoints."""
    if type(topic_id) is not int or topic_id < 1:
        raise ValueError("Topic ID must be a positive integer")
    os.makedirs(base, exist_ok=True)
    legacy = os.path.join(base, f"topic_{topic_id}")
    safe_title = (title or "Topic").encode("utf-8")[:180].decode("utf-8", errors="ignore")
    destination = group_folder(base, safe_title, topic_id)
    if os.path.basename(destination).casefold() == f"topic_{topic_id}".casefold():
        destination = group_folder(base, safe_title + " files", topic_id)
    candidates = []
    with os.scandir(base) as entries:
        for entry in entries:
            if not entry.name.endswith(f"_{topic_id}"):
                continue
            if entry.is_symlink():
                raise ValueError("Topic folders must not be symbolic links")
            if entry.path != legacy and entry.is_dir(follow_symlinks=False):
                candidates.append(entry.path)
    if len(candidates) > 1 or (candidates and os.path.lexists(legacy)):
        raise TopicFolderConflict("Multiple folders exist for this topic ID")
    if candidates:
        destination = candidates[0]
    if os.path.lexists(legacy):
        if not os.path.isdir(legacy):
            raise TopicFolderConflict("The legacy topic path is not a directory")
        if legacy != destination:
            os.rename(legacy, destination)
    if os.path.lexists(destination) and not os.path.isdir(destination):
        raise TopicFolderConflict("The topic path is not a directory")
    # Run even after a rename: an interrupted state write can be retried safely.
    if destination != legacy:
        old_tail = sync_key(channel_id, topic_id, folder=legacy).split(":destination:")[1]
        new_tail = sync_key(channel_id, topic_id, folder=destination).split(":destination:")[1]
        if old_tail == new_tail:
            return destination
        data = read_json(SYNC_FILE, {})
        changed = False
        for key, value in list(data.items()):
            if not key.startswith(f"{channel_id}:topic:{topic_id}:filter:") or not key.endswith(":destination:" + old_tail):
                continue
            if type(value) is int and value >= 0:
                target = key[:-len(old_tail)] + new_tail
                previous = data.get(target)
                data[target] = min(value, previous) if type(previous) is int and previous >= 0 else value
            del data[key]
            changed = True
        if changed:
            write_json(SYNC_FILE, data)
    return destination


def message_day(message):
    sent_at = getattr(message, "date", None)
    if sent_at is None:
        return None
    if sent_at.tzinfo is not None:
        sent_at = sent_at.astimezone(timezone.utc)
    return sent_at.date()


def legacy_media_filename(message):
    extension = getattr(getattr(message, "file", None), "ext", None) or ".bin"
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,10}", extension):
        extension = ".bin"
    return f"{message.id}{extension.lower()}"


def media_filename(message):
    legacy = legacy_media_filename(message)
    day = message_day(message)
    if day is None:
        return legacy
    stem, extension = os.path.splitext(legacy)
    return f"{stem}_{day.isoformat()}{extension}"


class _TransferCancelled(Exception):
    pass


class _FileTransfer:
    """Per-attempt byte progress, throttled to keep the UI responsive."""
    def __init__(self, downloader, filename, attempt, emit):
        self.downloader = downloader
        self.filename = filename
        self.attempt = attempt
        self.emit = emit
        self.started = time.monotonic()
        self.last_report = self.started
        self.paused_seconds = 0.0
        self.received = 0
        self.total = None

    def report(self, state, force=False):
        now = time.monotonic()
        if not force and now - self.last_report < 0.25:
            return
        self.last_report = now
        elapsed = max(0.0, now - self.started - self.paused_seconds)
        speed = self.received / elapsed if elapsed > 0 else 0.0
        if state != "downloading":
            speed = 0.0
        eta = max(0, self.total - self.received) / speed if self.total and speed > 0 else None
        self.emit(state, filename=self.filename, received=self.received,
                  total=self.total, speed=speed, eta=eta, attempt=self.attempt)

    async def update(self, received, total):
        self.received = max(0, int(received))
        self.total = int(total) if total is not None and total > 0 else None
        if self.downloader.paused and not self.downloader.cancelled:
            self.report("paused", force=True)
            paused_at = time.monotonic()
            while self.downloader.paused and not self.downloader.cancelled:
                await asyncio.sleep(0.1)
            self.paused_seconds += time.monotonic() - paused_at
        if self.downloader.cancelled:
            raise _TransferCancelled()
        self.report("downloading", force=bool(self.total and self.received >= self.total))


class TelegramDownloader:
    def __init__(self, api_id, api_hash, phone):
        self.phone = phone
        session_dir = ".telegram-downloader"
        if os.path.islink(session_dir):
            raise ValueError("Session directory must not be a symbolic link")
        os.makedirs(session_dir, mode=0o700, exist_ok=True)
        os.chmod(session_dir, 0o700)
        account_key = hashlib.sha256(phone.strip().encode("utf-8")).hexdigest()[:24]
        session_path = os.path.join(session_dir, f"account_{account_key}.session")
        # Create with private permissions before SQLite/Telethon opens it.
        if os.path.islink(session_path):
            raise ValueError("Session file must not be a symbolic link")
        fd = os.open(session_path, os.O_CREAT | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        os.chmod(session_path, 0o600)
        self.client = TelegramClient(
            session_path, api_id, api_hash,
            request_retries=15,
            connection_retries=15,
            retry_delay=5,
            timeout=120
        )
        self.paused = False
        self.cancelled = False
        self.otp_future = None

    async def connect(self, loop):
        await self.client.connect()
        if not await self.client.is_user_authorized():
            await self.client.send_code_request(self.phone)
            self.otp_future = loop.create_future()
            code = await self.otp_future
            await self.client.sign_in(self.phone, code)

    def submit_otp(self, code, loop):
        loop.call_soon_threadsafe(self.otp_future.set_result, code)

    async def get_channels(self):
        channels = []
        async for dialog in self.client.iter_dialogs():
            if dialog.is_channel or dialog.is_group:
                channels.append(dialog)
        return channels

    async def get_topics(self, channel):
        topics = {}
        seen_ids = set()
        offset_date = offset_id = offset_topic = 0
        while True:
            page = await self.client(GetForumTopicsRequest(
                **{TOPIC_PEER_ARGUMENT: channel.entity}, offset_date=offset_date,
                offset_id=offset_id, offset_topic=offset_topic, limit=100))
            valid = [t for t in page.topics if hasattr(t, "title")]
            fresh = [t for t in valid if t.id not in topics]
            topics.update((t.id, t) for t in valid)
            seen_ids.update(t.id for t in page.topics)
            total = getattr(page, "count", None)
            if not page.topics or (total is not None and len(seen_ids) >= total):
                break
            if not fresh:
                raise RuntimeError("Topic pagination did not advance")
            last = valid[-1]
            offset_date = last.date
            if not getattr(page, "order_by_create_date", False):
                top_message = next((m for m in page.messages if m.id == last.top_message), None)
                offset_date = getattr(top_message, "date", None) or last.date
            offset_id, offset_topic = last.top_message, last.id
        return sorted(topics.values(), key=lambda t: (t.id != 1, t.title.casefold(), t.id))

    async def find_senders(self, channel, query):
        query = query.strip()
        if not query:
            return []
        if re.fullmatch(r"-?[0-9]+", query):
            sender_id = int(query)
            if sender_id == 0:
                raise ValueError("Sender ID must be nonzero")
            return [utils.get_peer(sender_id)]
        if query.startswith("@"):
            entity = await self.client.get_entity(query)
            if not isinstance(entity, (User, Channel)):
                raise ValueError("Choose a user or channel sender")
            return [entity]
        matches = []
        async for user in self.client.iter_participants(channel.entity, search=query, limit=30):
            label = " ".join(filter(None, (getattr(user, "first_name", None),
                                            getattr(user, "last_name", None),
                                            getattr(user, "username", None))))
            if query.casefold() in label.casefold():
                matches.append(user)
        return matches

    def matches_filter(self, message, media_filter):
        if media_filter and "," in media_filter:
            return any(self.matches_filter(message, token.strip()) for token in media_filter.split(",") if token.strip())

        if not media_filter or media_filter == "all":
            return message.media is not None

        if media_filter == "photo":
            return isinstance(message.media, MessageMediaPhoto)

        if media_filter in ("video", "audio"):
            if isinstance(message.media, MessageMediaDocument):
                mime = message.media.document.mime_type
                return media_filter in mime
            return False

        if media_filter.startswith("."):
            extensions = [e.strip().lower() for e in media_filter.split(",")]

            # Match Telegram native photos for image extensions
            image_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
            if any(ext in image_exts for ext in extensions):
                if isinstance(message.media, MessageMediaPhoto):
                    return True

            # Match document filenames
            if isinstance(message.media, MessageMediaDocument):
                for attr in message.media.document.attributes:
                    if isinstance(attr, DocumentAttributeFilename):
                        fname = attr.file_name.lower()
                        return any(fname.endswith(ext) for ext in extensions)

        return False

    async def download(self, channel, folder, media_filter, limit_mode, custom_limit, reverse, on_progress, on_log, on_done, topic_id=None, reset_controls=True, cutoff_date=None, on_transfer=None, sender_id=None, include_discussions=False, parallel_downloads=2):
        if type(parallel_downloads) is not int or not 1 <= parallel_downloads <= 4:
            raise ValueError("Choose between 1 and 4 parallel downloads")
        if sender_id is not None and (type(sender_id) is not int or sender_id == 0):
            raise ValueError("Select a valid sender ID")
        forum = bool(getattr(channel.entity, "forum", False))
        if forum and (type(topic_id) is not int or topic_id < 1):
            raise ValueError("Select a topic before downloading from a forum.")
        if not forum and topic_id is not None:
            raise ValueError("Topics require a forum supergroup.")
        if reset_controls:
            self.paused = False
            self.cancelled = False
        os.makedirs(folder, exist_ok=True)
        include_discussions = bool(include_discussions and not forum
                                   and getattr(channel.entity, "broadcast", False))

        # ── File limit ──
        if limit_mode == "all":
            file_limit = None
        elif limit_mode == "custom":
            file_limit = custom_limit
        else:
            file_limit = int(limit_mode)

        count = 0
        skipped = 0
        last_skip_report = 0.0
        pending = set()
        reserved = set()
        active = {}
        cooldown_until = 0.0

        def notify(state, **details):
            nonlocal last_skip_report
            if on_transfer is None:
                return
            if state == "skipping":
                now = time.monotonic()
                if now - last_skip_report < 0.25:
                    return
                last_skip_report = now
            aggregate = sum(item.get("speed", 0) for item in active.values()
                            if item.get("state") == "downloading")
            if self.paused or self.cancelled or time.monotonic() < cooldown_until:
                aggregate = 0.0
            on_transfer(dict(state=state, downloaded=count, skipped=skipped,
                             limit=file_limit, active=len(active), parallel_limit=parallel_downloads,
                             aggregate_speed=aggregate, **details))

        if file_limit is not None and (type(file_limit) is not int or file_limit < 1):
            raise ValueError("File limit must be positive")
        # A discussion window counts parent messages, never files from their replies.
        parent_limit = file_limit if include_discussions else None
        if include_discussions:
            file_limit = None

        # A restricted date scan must not change or depend on the unrestricted checkpoint.
        use_checkpoint = limit_mode == "all" and cutoff_date is None
        last_id = load_last_id(channel.id, topic_id, media_filter, folder, sender_id) if use_checkpoint else 0
        high_id = last_id
        complete = True
        if include_discussions and parent_limit:
            on_log(f"🔍 Scanning up to {parent_limit} channel messages and their discussions...")
        elif last_id:
            on_log(f"🔄 Resuming from message ID {last_id}...")
        else:
            on_log(f"🔍 Scanning for {file_limit or 'all'} matching files...")

        direction = "Oldest → Newest" if reverse else "Newest → Oldest"
        on_log(f"📅 Order: {direction}")
        if cutoff_date is not None:
            relation = "on or after" if reverse else "on or before"
            on_log(f"Message dates {relation} {cutoff_date.isoformat()} (UTC).")

        notify("scanning")

        seen_discussions = set()
        if include_discussions:
            on_log("💬 Including discussions only for channel messages in this download scope.")

        async def ready():
            while not self.cancelled:
                delay = cooldown_until - time.monotonic()
                if not self.paused and delay <= 0:
                    return True
                await asyncio.sleep(min(0.1, delay) if delay > 0 else 0.5)
            return not self.cancelled

        def finish_thread(thread):
            nonlocal complete
            if (not thread["enumerated"] or thread["pending"] or thread["saved"]
                    or not thread["complete"] or self.cancelled or not use_checkpoint):
                return
            try:
                save_last_id(channel.id, thread["high"], None, media_filter,
                             thread["folder"], sender_id, thread["identity"])
                thread["saved"] = True
            except Exception:
                thread["complete"] = complete = False
                on_log("Could not save discussion sync. It can be retried without skipping unfinished files.")

        async def reap(wait=False):
            nonlocal complete
            if self.cancelled:
                for task in pending:
                    task.cancel()
            if not pending:
                return
            done = {task for task in pending if task.done()}
            if wait and not done:
                done, _ = await asyncio.wait(pending, timeout=0.1,
                                             return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                pending.remove(task)
                try:
                    task.result()
                except asyncio.CancelledError:
                    complete = False
                except Exception:
                    complete = False
                    on_log("A file could not be processed; unfinished sync was retained.")

        async def watch_cancel():
            # A timer keeps cancellation responsive even if a network read stalls.
            tick = asyncio.Event()
            while True:
                if self.cancelled:
                    for task in pending:
                        task.cancel()
                    return
                try:
                    await asyncio.wait_for(tick.wait(), timeout=0.1)
                except asyncio.TimeoutError:
                    pass

        async def run_file(message, destination_folder, filename, destination, thread):
            nonlocal complete
            succeeded = False
            try:
                succeeded = await transfer_media(message, destination_folder, filename, destination)
            finally:
                if not succeeded:
                    complete = False
                    if thread is not None:
                        thread["complete"] = False
                reserved.discard(destination)
                active.pop(destination, None)
                if thread is not None:
                    thread["pending"] -= 1
                    finish_thread(thread)

        async def transfer_media(message, destination_folder, filename, destination):
            nonlocal count, cooldown_until
            def emit_file(state, **details):
                if state in ("file_complete", "failed"):
                    active.pop(destination, None)
                else:
                    active[destination] = dict(state=state, **details)
                notify(state, **details)

            succeeded = False
            for attempt in range(5):
                if not await ready():
                    break
                temporary = None
                transfer = _FileTransfer(self, filename, attempt + 1, emit_file)
                transfer.report("starting", force=True)
                async def progress(received, total):
                    await transfer.update(received, total)
                    if not await ready():
                        raise _TransferCancelled()
                try:
                    fd, temporary = tempfile.mkstemp(prefix=".telegram-", suffix=".part", dir=destination_folder)
                    with os.fdopen(fd, "wb") as output:
                        if on_transfer:
                            path = await message.download_media(file=output, progress_callback=progress)
                        else:
                            path = await message.download_media(file=output)
                        if path:
                            transfer.received = output.tell()
                            transfer.total = transfer.received
                    if not path:
                        raise RuntimeError("Telegram returned no media")
                    if not await ready():
                        break
                    if os.path.islink(destination):
                        raise ValueError("Download destination must not be a symbolic link")
                    os.replace(temporary, destination)
                    temporary = None
                    succeeded = True
                    count += 1
                    break
                except _TransferCancelled:
                    break
                except FloodWaitError as error:
                    seconds = max(0, int(error.seconds))
                    cooldown_until = max(cooldown_until, time.monotonic() + seconds)
                    for item in active.values():
                        item["speed"] = 0.0
                    transfer.report("rate_limited", force=True)
                    on_log(f"Telegram requested a {seconds}s wait. Downloads will resume automatically.")
                    if not await ready():
                        break
                except Exception:
                    transfer.report("retrying" if attempt < 4 else "failed", force=True)
                    on_log(f"⚠ Download attempt {attempt + 1} failed.")
                    if attempt < 4 and not self.cancelled:
                        await asyncio.sleep(1)
                finally:
                    if temporary is not None:
                        os.unlink(temporary)
            if succeeded:
                # Reporting failures must never retry a file already committed.
                transfer.report("file_complete", force=True)
                fraction = 0.0 if not file_limit else min(count / file_limit, 1.0)
                on_log(f"✅ [{count}/{file_limit or '∞'}] {filename}")
                on_progress(count, skipped, fraction)
            elif not self.cancelled:
                on_log(f"❌ Could not download message {message.id}; sync not advanced.")
            return succeeded

        async def process_media(message, destination_folder, thread=None):
            nonlocal count, skipped
            if sender_id is not None and getattr(message, "sender_id", None) != sender_id:
                return True

            if not message.media:
                return True

            if cutoff_date is not None:
                day = message_day(message)
                if day is None or (reverse and day < cutoff_date) or (not reverse and day > cutoff_date):
                    return True

            # Check match first — no disk read
            if not self.matches_filter(message, media_filter):
                return True

            filename = media_filename(message)
            destination = os.path.join(destination_folder, filename)
            if os.path.islink(destination):
                raise ValueError("Download destination must not be a symbolic link")
            legacy_destination = os.path.join(destination_folder, legacy_media_filename(message))
            if destination in reserved or os.path.isfile(destination) or (
                legacy_destination != destination
                and not os.path.islink(legacy_destination)
                and os.path.isfile(legacy_destination)
            ):
                on_log(f"⏭ Already exists: {message.id}")
                skipped += 1
                notify("skipping", filename=filename)
                return True

            await reap()
            while pending and (len(pending) >= parallel_downloads
                               or (file_limit and count + len(pending) >= file_limit)):
                await reap(wait=True)
            if not await ready():
                return False
            if file_limit and count >= file_limit:
                return True
            reserved.add(destination)
            if thread is not None:
                thread["pending"] += 1
            pending.add(asyncio.create_task(run_file(
                message, destination_folder, filename, destination, thread)))
            return True

        async def scan():
            nonlocal complete, high_id
            # Discussion reads use the same parent window as this run. All mode resumes
            # from the channel checkpoint instead of revisiting older channel history.
            scope = {"reply_to": topic_id} if forum and topic_id != 1 else {}
            if include_discussions and cutoff_date is not None:
                # Jump directly to the inclusive date boundary instead of paging past
                # newer/older posts. Keep a local check for Telegram's second precision.
                try:
                    boundary = datetime.combine(cutoff_date, datetime.min.time(), tzinfo=timezone.utc)
                    boundary += timedelta(seconds=-1) if reverse else timedelta(days=1)
                    if 0 < boundary.timestamp() < 2**31:
                        scope["offset_date"] = boundary
                except OverflowError:
                    pass
            async for message in self.client.iter_messages(
                channel.entity, limit=parent_limit, wait_time=0, reverse=reverse,
                min_id=last_id, **scope
            ):
                if not await ready():
                    complete = False
                    on_log("⛔ Download cancelled.")
                    break
                if not message_in_topic(message, topic_id):
                    continue
                if include_discussions and cutoff_date is not None:
                    day = message_day(message)
                    if day is None or (reverse and day < cutoff_date) or (not reverse and day > cutoff_date):
                        continue
                high_id = max(high_id, message.id)
                if message.id > last_id:
                    complete = await process_media(message, folder) and complete
                if self.cancelled or (file_limit and count >= file_limit):
                    break

                replies = getattr(message, "replies", None)
                if not (include_discussions and getattr(replies, "comments", False)
                        and getattr(replies, "replies", 0)):
                    continue
                group_id = getattr(replies, "channel_id", None)
                thread = None
                try:
                    if type(group_id) is not int or group_id < 1:
                        raise ValueError("Missing discussion group")
                    if not await ready():
                        break
                    notify("scanning", filename=f"Discussion for post {message.id}")
                    discussion = await self.client(GetDiscussionMessageRequest(
                        peer=channel.entity, msg_id=message.id))
                    marked_group_id = utils.get_peer_id(PeerChannel(group_id))
                    group = next(c for c in discussion.chats if c.id == group_id)
                    # Telegram returns an album's initial messages newest first; the
                    # last is the thread root. Album posts must share one destination.
                    root = next(m for m in reversed(discussion.messages)
                                if m.chat_id == marked_group_id)
                    identity = (group_id, root.id)
                    if identity in seen_discussions:
                        continue
                    seen_discussions.add(identity)
                    target = discussion_folder(folder, *identity)
                    comment_last = load_last_id(channel.id, None, media_filter, target,
                                                sender_id, identity) if use_checkpoint else 0
                    comment_high = comment_last
                    thread = dict(identity=identity, folder=target, high=comment_last,
                                  complete=True, pending=0, enumerated=False, saved=False)
                    on_log(f"💬 Scanning discussion for post {message.id}.")
                    async for comment in self.client.iter_messages(
                        group, reply_to=root.id, limit=None, wait_time=0,
                        reverse=reverse, min_id=comment_last
                    ):
                        if not await ready():
                            thread["complete"] = False
                            break
                        if comment.id == root.id:
                            continue
                        reply = getattr(comment, "reply_to", None)
                        thread_id = (getattr(reply, "reply_to_top_id", None)
                                     or getattr(reply, "reply_to_msg_id", None))
                        if comment.chat_id != marked_group_id or thread_id != root.id:
                            thread["complete"] = False
                            continue
                        comment_high = max(comment_high, comment.id)
                        thread["high"] = comment_high
                        thread["complete"] = await process_media(comment, target, thread) and thread["complete"]
                        if self.cancelled or (file_limit and count >= file_limit):
                            break
                    thread["enumerated"] = True
                    finish_thread(thread)
                    if not thread["complete"]:
                        complete = False
                        on_log(f"Discussion for post {message.id} was incomplete; its sync was not advanced.")
                except Exception:
                    if thread is not None:
                        thread["complete"] = False
                        thread["enumerated"] = True
                    # Access can differ between a channel and its linked group.
                    complete = False
                    on_log(f"⚠ Could not load discussion for post {message.id}. "
                           "Check group access, connection and folder permissions; its sync was not advanced.")
                if self.cancelled or (file_limit and count >= file_limit):
                    break

        watcher = asyncio.create_task(watch_cancel())
        try:
            await scan()
            while pending:
                await reap(wait=True)
        finally:
            watcher.cancel()
            for task in pending:
                task.cancel()
            await asyncio.gather(watcher, *pending, return_exceptions=True)
            pending.clear()

        if file_limit and count >= file_limit:
            on_log(f"🎯 Reached target of {file_limit} files. Stopping.")
        if include_discussions and not seen_discussions and complete and not self.cancelled:
            on_log("No post discussions with replies were found in this download scope.")

        if complete and not self.cancelled and use_checkpoint:
            save_last_id(channel.id, high_id, topic_id, media_filter, folder, sender_id)
        if not complete or self.cancelled:
            on_log("Download stopped; unfinished scopes kept their previous sync positions.")
        on_done(count, skipped)
        status = "cancelled" if self.cancelled else ("complete" if complete else "incomplete")
        notify("scope_" + status)
        return status

