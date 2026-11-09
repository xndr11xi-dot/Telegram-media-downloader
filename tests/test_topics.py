import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch, AsyncMock
import downloader as d


def message(mid, topic=None):
    reply = None if topic is None else NS(forum_topic=True, reply_to_top_id=topic, reply_to_msg_id=999)
    m = NS(id=mid, reply_to=reply, media=object())
    m.download_media = AsyncMock(return_value=f'/tmp/{mid}.bin')
    return m


class TopicsTest(unittest.IsolatedAsyncioTestCase):
    def test_membership(self):
        self.assertTrue(d.message_in_topic(message(4), 1))
        self.assertFalse(d.message_in_topic(message(4), 7))
        self.assertTrue(d.message_in_topic(message(4, 7), 7))
        self.assertFalse(d.message_in_topic(message(4, 7), 1))
        direct = message(4, 7)
        direct.reply_to.reply_to_top_id = None
        direct.reply_to.reply_to_msg_id = 7
        self.assertTrue(d.message_in_topic(direct, 7))
        self.assertTrue(d.message_in_topic(direct, None))

    async def test_download_scope_and_checkpoint(self):
        for reverse in (False, True):
            with tempfile.TemporaryDirectory() as folder, patch.object(d, 'SYNC_FILE', str(Path(folder)/'sync.json')), patch.object(d.asyncio, 'sleep', new=AsyncMock()):
                messages = [message(30, 8), message(20, 7), message(10, 7)]
                if reverse:
                    messages.reverse()
                calls = []
                async def iterate(*args, **kwargs):
                    calls.append(kwargs)
                    for m in messages:
                        yield m
                downloader = d.TelegramDownloader.__new__(d.TelegramDownloader)
                downloader.client = NS(iter_messages=iterate)
                channel = NS(id=-100123, entity=NS(forum=True))
                await downloader.download(channel, folder, 'all', 'all', 20, reverse, lambda *a: None, lambda *a: None, lambda *a: None, topic_id=7)
                messages[[m.id for m in messages].index(30)].download_media.assert_not_awaited()
                self.assertEqual(d.load_last_id(channel.id, 7, 'all'), 20)
                self.assertEqual(d.load_last_id(channel.id, 8, 'all'), 0)
                self.assertEqual(d.load_last_id(channel.id), 0)
                self.assertEqual(d.load_last_id(channel.id, 7, '.pdf'), 0)
                self.assertEqual(calls[0]['min_id'], 0)

    async def test_normal_channel_and_failed_retry(self):
        for forum, failure in ((False, False), (True, True)):
            with tempfile.TemporaryDirectory() as folder, patch.object(d, 'SYNC_FILE', str(Path(folder)/'sync.json')), patch.object(d.asyncio, 'sleep', new=AsyncMock()):
                m = message(20, 7 if forum else None)
                if failure:
                    m.download_media.side_effect = OSError('offline')
                async def iterate(*args, **kwargs):
                    yield m
                downloader = d.TelegramDownloader.__new__(d.TelegramDownloader)
                downloader.client = NS(iter_messages=iterate)
                await downloader.download(NS(id=12, entity=NS(forum=forum)), folder, 'all', 'all', 20, False, lambda *a: None, lambda *a: None, lambda *a: None, topic_id=7 if forum else None)
                self.assertEqual(d.load_last_id(12, 7 if forum else None, 'all'), 0 if failure else 20)
                self.assertEqual(m.download_media.await_count, 5 if failure else 1)

    async def test_topic_pagination(self):
        topic = NS(id=7, title='Files', top_message=90, date=1)
        client = AsyncMock(side_effect=[NS(topics=[topic], messages=[NS(id=90, date=2)]), NS(topics=[], messages=[])])
        downloader = d.TelegramDownloader.__new__(d.TelegramDownloader)
        downloader.client = client
        self.assertEqual(await downloader.get_topics(NS(entity=object())), [topic])
        self.assertEqual(client.call_args_list[1].args[0].offset_topic, 7)

    async def test_cancel_does_not_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(d, 'SYNC_FILE', str(Path(folder)/'sync.json')):
            downloader = d.TelegramDownloader.__new__(d.TelegramDownloader)
            async def iterate(*args, **kwargs):
                downloader.cancelled = True
                yield message(20, 7)
            downloader.client = NS(iter_messages=iterate)
            await downloader.download(NS(id=12, entity=NS(forum=True)), folder, 'all', 'all', 20, False, lambda *a: None, lambda *a: None, lambda *a: None, topic_id=7)
            self.assertEqual(d.load_last_id(12, 7, 'all'), 0)


if __name__ == '__main__':
    unittest.main()
