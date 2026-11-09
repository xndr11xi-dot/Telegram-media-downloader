from telethon import TelegramClient
from telethon.tl.functions.channels import GetForumTopicsRequest
from telethon.tl.types import (
    MessageMediaPhoto,
    MessageMediaDocument,
    DocumentAttributeFilename
)
import asyncio
import os
import json

# ── Incremental sync ──
SYNC_FILE = "sync_state.json"

def sync_key(channel_id, topic_id=None, media_filter=None):
    if topic_id is None:
        return str(channel_id)
    return f"{channel_id}:topic:{topic_id}:filter:{media_filter or 'all'}"


def message_in_topic(message, topic_id):
    if topic_id is None:
        return True
    reply = getattr(message, "reply_to", None)
    if reply and getattr(reply, "forum_topic", False):
        root = getattr(reply, "reply_to_top_id", None) or reply.reply_to_msg_id
        return root == topic_id
    # General also contains ordinary replies without forum_topic set.
    return topic_id == 1


def load_last_id(channel_id, topic_id=None, media_filter=None):
    if os.path.exists(SYNC_FILE):
        with open(SYNC_FILE, "r") as f:
            data = json.load(f)
        return data.get(sync_key(channel_id, topic_id, media_filter), 0)
    return 0

def save_last_id(channel_id, message_id, topic_id=None, media_filter=None):
    data = {}
    if os.path.exists(SYNC_FILE):
        with open(SYNC_FILE, "r") as f:
            data = json.load(f)
    key = sync_key(channel_id, topic_id, media_filter)
    data[key] = max(data.get(key, 0), message_id)
    with open(SYNC_FILE, "w") as f:
        json.dump(data, f, indent=2)


class TelegramDownloader:
    def __init__(self, api_id, api_hash, phone):
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.client = TelegramClient(
            f"session_{phone}", api_id, api_hash,
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
                channel=channel.entity, offset_date=offset_date,
                offset_id=offset_id, offset_topic=offset_topic, limit=100))
            valid = [t for t in page.topics if hasattr(t, "title")]
            fresh = [t for t in valid if t.id not in topics]
            topics.update((t.id, t) for t in valid)
            if not fresh:
                break
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

    async def download(self, channel, folder, media_filter, limit_mode, custom_limit, reverse, on_progress, on_log, on_done, topic_id=None):
        if getattr(channel.entity, "forum", False) and topic_id is None:
            raise ValueError("Select a topic before downloading from a forum.")
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

        # ── Read existing files once — no repeated disk reads ──
        existing_files = set(os.listdir(folder))

        # ── Incremental sync only for "All" mode ──
        last_id = load_last_id(channel.id, topic_id, media_filter) if limit_mode == "all" else 0
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

            # Check already downloaded from cached set
            if any(f.startswith(str(message.id)) for f in existing_files):
                on_log(f"⏭ Already exists: {message.id}")
                skipped += 1
                continue

            # Match found — download immediately
            path = None
            for attempt in range(5):
                try:
                    path = await message.download_media(file=folder)
                    if path:
                        count += 1
                        existing_files.add(os.path.basename(path))

                        # ── Division by zero fix ──
                        fraction = 0.0 if not file_limit else min(count / file_limit, 1.0)

                        on_log(f"✅ [{count}/{file_limit or '∞'}] {os.path.basename(path)}")
                        on_progress(count, skipped, fraction)

                        # ── Save last ID for incremental sync ──
                        # Commit the checkpoint only after the entire scan succeeds.

                        # ── Sleep to prevent Telegram rate limiting ──
                        await asyncio.sleep(1)

                    break
                except Exception as e:
                    on_log(f"⚠ Retry {attempt + 1}: {e}")
                    await asyncio.sleep(10)
            else:
                complete = False

            if not path:
                complete = False

            if file_limit and count >= file_limit:
                on_log(f"🎯 Reached target of {file_limit} files. Stopping.")
                break

        if complete and not self.cancelled and limit_mode == "all":
            save_last_id(channel.id, high_id, topic_id, media_filter)
        on_done(count, skipped)

