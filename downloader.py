from telethon import TelegramClient
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
    DocumentAttributeFilename
)
import asyncio
import os
import json
import hashlib
import re
import tempfile
from local_data import read_json, write_json

# ── Incremental sync ──
SYNC_FILE = "sync_state.json"

def sync_key(channel_id, topic_id=None, media_filter=None, folder=None):
    filters = sorted(set(x.strip().lower() for x in (media_filter or "all").split(",")))
    scope = f"{channel_id}:topic:{topic_id}:filter:{','.join(filters)}"
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


def load_last_id(channel_id, topic_id=None, media_filter=None, folder=None):
    data = read_json(SYNC_FILE, {})
    value = data.get(sync_key(channel_id, topic_id, media_filter, folder), 0)
    return value if type(value) is int and value >= 0 else 0


def save_last_id(channel_id, message_id, topic_id=None, media_filter=None, folder=None):
    data = read_json(SYNC_FILE, {})
    key = sync_key(channel_id, topic_id, media_filter, folder)
    previous = data.get(key, 0)
    data[key] = max(previous if type(previous) is int else 0, message_id)
    write_json(SYNC_FILE, data)


def group_folder(base, name, channel_id):
    # Telegram titles cannot introduce path components or parent traversal.
    component = re.sub(r"[^\w .-]", "_", name).strip(" .")[:80] or "group"
    return os.path.join(base, f"{component}_{channel_id}")


def media_filename(message):
    extension = getattr(getattr(message, "file", None), "ext", None) or ".bin"
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,10}", extension):
        extension = ".bin"
    return f"{message.id}{extension.lower()}"


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
        offset_date = offset_id = offset_topic = 0
        while True:
            page = await self.client(GetForumTopicsRequest(
                **{TOPIC_PEER_ARGUMENT: channel.entity}, offset_date=offset_date,
                offset_id=offset_id, offset_topic=offset_topic, limit=100))
            valid = [t for t in page.topics if hasattr(t, "title")]
            fresh = [t for t in valid if t.id not in topics]
            topics.update((t.id, t) for t in valid)
            if not page.topics:
                break
            if not fresh:
                raise RuntimeError("Topic pagination did not advance")
            last = valid[-1]
            messages = {m.id: m for m in page.messages}
            offset_date = getattr(messages.get(last.top_message), "date", last.date)
            offset_id, offset_topic = last.top_message, last.id
        return sorted(topics.values(), key=lambda t: (t.id != 1, t.title.casefold(), t.id))

    def matches_filter(self, message, media_filter):
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

    async def download(self, channel, folder, media_filter, limit_mode, custom_limit, reverse, on_progress, on_log, on_done, topic_id=None, reset_controls=True):
        forum = bool(getattr(channel.entity, "forum", False))
        if forum and (type(topic_id) is not int or topic_id < 1):
            raise ValueError("Select a topic before downloading from a forum.")
        if not forum and topic_id is not None:
            raise ValueError("Topics require a forum supergroup.")
        if reset_controls:
            self.paused = False
            self.cancelled = False
        os.makedirs(folder, exist_ok=True)

        # ── File limit ──
        if limit_mode == "all":
            file_limit = None
        elif limit_mode == "custom":
            file_limit = custom_limit
        else:
            file_limit = int(limit_mode)

        count = 0
        skipped = 0

        if file_limit is not None and (type(file_limit) is not int or file_limit < 1):
            raise ValueError("File limit must be positive")

        # ── Incremental sync only for "All" mode ──
        last_id = load_last_id(channel.id, topic_id, media_filter, folder) if limit_mode == "all" else 0
        high_id = last_id
        complete = True
        if last_id:
            on_log(f"🔄 Resuming from message ID {last_id}...")
        else:
            on_log(f"🔍 Scanning for {file_limit or 'all'} matching files...")

        direction = "Oldest → Newest" if reverse else "Newest → Oldest"
        on_log(f"📅 Order: {direction}")

        async for message in self.client.iter_messages(
            channel.id,
            limit=None,
            wait_time=0,
            reverse=reverse,
            min_id=last_id
        ):
            while self.paused and not self.cancelled:
                await asyncio.sleep(0.5)

            if self.cancelled:
                complete = False
                on_log("⛔ Download cancelled.")
                break

            if not message_in_topic(message, topic_id):
                continue
            high_id = max(high_id, message.id)

            if not message.media:
                continue

            # Check match first — no disk read
            if not self.matches_filter(message, media_filter):
                continue

            filename = media_filename(message)
            destination = os.path.join(folder, filename)
            if os.path.islink(destination):
                raise ValueError("Download destination must not be a symbolic link")
            if os.path.isfile(destination):
                on_log(f"⏭ Already exists: {message.id}")
                skipped += 1
                continue

            succeeded = False
            for attempt in range(5):
                while self.paused and not self.cancelled:
                    await asyncio.sleep(0.5)
                if self.cancelled:
                    break
                temporary = None
                try:
                    # Passing a stream prevents Telegram filenames from escaping the folder.
                    fd, temporary = tempfile.mkstemp(prefix=".telegram-", suffix=".part", dir=folder)
                    with os.fdopen(fd, "wb") as output:
                        path = await message.download_media(file=output)
                    if not path:
                        raise RuntimeError("Telegram returned no media")
                    if self.cancelled:
                        break
                    os.replace(temporary, destination)
                    temporary = None
                    succeeded = True
                    count += 1
                    fraction = 0.0 if not file_limit else min(count / file_limit, 1.0)
                    on_log(f"✅ [{count}/{file_limit or '∞'}] {filename}")
                    on_progress(count, skipped, fraction)
                    await asyncio.sleep(1)
                    break
                except Exception:
                    # Never log exception text: it may include request secrets or paths.
                    on_log(f"⚠ Download attempt {attempt + 1} failed.")
                    if attempt < 4 and not self.cancelled:
                        await asyncio.sleep(1)
                finally:
                    if temporary is not None:
                        os.unlink(temporary)
            if not succeeded:
                complete = False
                if not self.cancelled:
                    on_log(f"❌ Could not download message {message.id}; sync not advanced.")

            if file_limit and count >= file_limit:
                on_log(f"🎯 Reached target of {file_limit} files. Stopping.")
                break

        if complete and not self.cancelled and limit_mode == "all":
            save_last_id(channel.id, high_id, topic_id, media_filter, folder)
        if not complete or self.cancelled:
            on_log("Download stopped without advancing sync.")
        on_done(count, skipped)
        return "cancelled" if self.cancelled else ("complete" if complete else "incomplete")

