"""All Telegram objects and downloads are synthetic; no account or network needed."""
import asyncio
import json
import inspect
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from telethon.tl.types import (
    Document, DocumentAttributeFilename, MessageMediaDocument, MessageMediaPhoto,
    MessageReplyHeader, ForumTopic, ForumTopicDeleted,
)
import downloader as d
from local_data import read_json, write_json


def message(mid, topic=None, extension='.bin', media=None):
    reply = None if topic is None else MessageReplyHeader(
        forum_topic=True, reply_to_top_id=topic, reply_to_msg_id=999)
    m = NS(id=mid, reply_to=reply, media=media or MessageMediaPhoto(), file=NS(ext=extension))
    async def download(file):
        file.write(b'synthetic media fixture')
        return file
    m.download_media = AsyncMock(side_effect=download)
    return m


def document(mid, topic, name, mime):
    media = MessageMediaDocument(document=Document(
        id=1, access_hash=0, file_reference=b'', date=None, mime_type=mime,
        size=20, dc_id=1, attributes=[DocumentAttributeFilename(file_name=name)]))
    return message(mid, topic, Path(name).suffix, media)


def topic(tid, title='Files'):
    extra = {}
    if "peer" in inspect.signature(ForumTopic).parameters:
        extra.update(peer=None, unread_poll_votes_count=0)
    return ForumTopic(**extra, id=tid, date=1, title=title, icon_color=0, top_message=tid+100,
                      read_inbox_max_id=0, read_outbox_max_id=0, unread_count=0,
                      unread_mentions_count=0, unread_reactions_count=0,
                      from_id=None, notify_settings=None)


class DownloadsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = str(Path(self.temp.name)/'media')
        self.sync = str(Path(self.temp.name)/'state.json')
        self.patch = patch.object(d, 'SYNC_FILE', self.sync)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.downloader = d.TelegramDownloader.__new__(d.TelegramDownloader)
        self.logs, self.progress, self.done, self.requests = [], [], [], []
        self.messages = []
        self.iter_error = None
        async def iterate(entity, **kwargs):
            self.requests.append((entity, kwargs))
            items = sorted(self.messages, key=lambda m:m.id, reverse=not kwargs['reverse'])
            for m in items:
                if m.id > kwargs['min_id']:
                    yield m
            if self.iter_error:
                raise self.iter_error
        self.downloader.client = NS(iter_messages=iterate)
        self.channel = NS(id=-10042, entity=NS(forum=True))

    async def run_download(self, topic_id=7, media_filter='all', mode='all', reverse=False):
        return await self.downloader.download(
            self.channel, self.folder, media_filter, mode, 2, reverse,
            lambda *a: self.progress.append(a), self.logs.append,
            lambda *a:self.done.append(a), topic_id=topic_id)

    def checkpoint(self, tid=7, media_filter='all', folder=None):
        return d.load_last_id(self.channel.id, tid, media_filter, folder or self.folder)

    async def test_named_topic_requests_thread_before_downloading(self):
        target, unrelated = message(20, 7), message(30, 8)
        async def iterate(entity, **kwargs):
            self.assertIs(entity, self.channel.entity)
            self.assertEqual(kwargs.get('reply_to'), 7)
            # A defensive client filter must still reject unrelated results.
            yield unrelated
            yield target
        self.downloader.client.iter_messages = iterate
        with patch.object(d.asyncio, 'sleep', new=AsyncMock()):
            self.assertEqual(await self.run_download(), 'complete')
        target.download_media.assert_awaited_once()
        unrelated.download_media.assert_not_awaited()
        self.assertEqual(self.done, [(1, 0)])

    async def test_general_and_regular_channels_do_not_request_reply_thread(self):
        for forum, tid in [(True, 1), (False, None)]:
            self.channel.entity.forum = forum
            self.messages = [message(10)]
            with patch.object(d.asyncio, 'sleep', new=AsyncMock()):
                await self.run_download(topic_id=tid, mode='1')
            self.assertNotIn('reply_to', self.requests[-1][1])
            self.assertIs(self.requests[-1][0], self.channel.entity)

    async def test_topic_isolation_both_orders_and_incremental_rerun(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse), patch.object(d.asyncio, 'sleep', new=AsyncMock()):
                self.messages = [message(30, 8), message(20, 7), message(10, 7)]
                await self.run_download(reverse=reverse)
                self.assertEqual(self.checkpoint(), 20)
                self.assertEqual(self.checkpoint(8), 0)
                self.assertEqual(self.checkpoint(None), 0)
                self.assertEqual(self.checkpoint(media_filter='.pdf'), 0)
                self.messages[0].download_media.assert_not_awaited()
                new = message(40, 7)
                self.messages.append(new)
                await self.run_download(reverse=reverse)
                self.assertEqual(self.requests[-1][1]['min_id'], 20)
                new.download_media.assert_awaited_once()
                self.assertEqual(self.checkpoint(), 40)
                # Reset only synthetic state for the next ordering subtest.
                Path(self.sync).unlink()
                for f in Path(self.folder).iterdir():
                    f.unlink()

    async def test_general_excludes_other_topic_but_includes_ordinary_replies(self):
        self.messages = [message(1), message(2, 7), message(3, 1), message(4)]
        self.messages[-1].reply_to = MessageReplyHeader(reply_to_msg_id=1)
        with patch.object(d.asyncio, 'sleep', new=AsyncMock()):
            await self.run_download(topic_id=1)
        self.assertEqual(sorted(p.name for p in Path(self.folder).iterdir()), ['1.bin','3.bin','4.bin'])

    async def test_normal_channel(self):
        self.channel.entity.forum = False
        self.messages = [message(9)]
        with patch.object(d.asyncio, 'sleep', new=AsyncMock()):
            self.assertEqual(await self.run_download(topic_id=None), 'complete')
        self.assertEqual(self.checkpoint(None), 9)

    async def test_media_filter_applies_inside_topic_before_limit(self):
        self.messages = [document(9,8,'other.pdf','application/pdf'),
                         document(8,7,'movie.mp4','video/mp4'),
                         document(7,7,'report.PDF','application/pdf'), message(6,7)]
        with patch.object(d.asyncio, 'sleep', new=AsyncMock()):
            await self.run_download(media_filter='.pdf', mode='1')
        self.assertEqual(self.done[-1], (1,0))
        self.assertTrue(Path(self.folder,'7.pdf').is_file())
        self.assertEqual(self.checkpoint(media_filter='.pdf'), 0)
        for m in self.messages:
            self.assertEqual(m.download_media.await_count, int(m.id == 7))

    async def test_duplicate_exact_match_and_numeric_prefix_collision(self):
        Path(self.folder).mkdir()
        Path(self.folder,'123.bin').write_bytes(b'synthetic existing media')
        exact, different = message(123,7), message(12,7)
        self.messages = [exact,different]
        with patch.object(d.asyncio, 'sleep', new=AsyncMock()):
            await self.run_download()
            await self.run_download(mode='2')
        exact.download_media.assert_not_awaited()
        different.download_media.assert_awaited_once()
        self.assertEqual(self.done[0], (1,1))
        self.assertEqual(self.done[1], (0,2))

    async def test_failed_retry_partial_cleanup_and_no_checkpoint(self):
        failed = message(20,7)
        async def fail(file):
            file.write(b'partial fixture')
            raise OSError('SYNTHETIC_SECRET_MUST_NOT_APPEAR')
        failed.download_media.side_effect = fail
        self.messages = [failed,message(10,7)]
        with patch.object(d.asyncio, 'sleep', new=AsyncMock()):
            self.assertEqual(await self.run_download(), 'incomplete')
        self.assertEqual(failed.download_media.await_count, 5)
        self.assertEqual(self.checkpoint(),0)
        self.assertFalse(Path(self.folder,'20.bin').exists())
        self.assertFalse(list(Path(self.folder).glob('*.part')))
        self.assertNotIn('SYNTHETIC_SECRET', '\n'.join(self.logs))

    async def test_transient_error_retry_succeeds(self):
        m = message(20,7)
        good = m.download_media.side_effect
        attempts = 0
        async def retry(file):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OSError('synthetic failure')
            return await good(file)
        m.download_media.side_effect = retry
        self.messages = [m]
        with patch.object(d.asyncio, 'sleep', new=AsyncMock()):
            self.assertEqual(await self.run_download(), 'complete')
        self.assertEqual(m.download_media.await_count,2)
        self.assertEqual(self.checkpoint(),20)

    async def test_empty_media_response_does_not_checkpoint(self):
        m = message(20,7)
        m.download_media = AsyncMock(return_value=None)
        self.messages = [m]
        with patch.object(d.asyncio, 'sleep', new=AsyncMock()):
            self.assertEqual(await self.run_download(), 'incomplete')
        self.assertEqual(self.checkpoint(),0)

    async def test_history_error_does_not_checkpoint_or_call_done(self):
        self.messages = [message(20,7)]
        self.iter_error = RuntimeError('synthetic API failure')
        with patch.object(d.asyncio, 'sleep', new=AsyncMock()), self.assertRaises(RuntimeError):
            await self.run_download()
        self.assertEqual(self.checkpoint(),0)
        self.assertEqual(self.done,[])

    async def test_pause_resume(self):
        m = message(20,7)
        self.messages = [m]
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.downloader.client.iter_messages
        async def iterate(*args, **kwargs):
            self.downloader.paused = True
            entered.set()
            await release.wait()
            async for item in original(*args, **kwargs):
                yield item
        self.downloader.client.iter_messages = iterate
        real_sleep = asyncio.sleep
        async def sleep(seconds):
            if seconds == 0.5:
                m.download_media.assert_not_awaited()
                self.downloader.paused = False
            await real_sleep(0)
        with patch.object(d.asyncio,'sleep',side_effect=sleep):
            task = asyncio.create_task(self.run_download())
            await entered.wait()
            m.download_media.assert_not_awaited()
            release.set()
            self.assertEqual(await task,'complete')
        m.download_media.assert_awaited_once()

    async def test_cancel_before_scheduled_download_starts(self):
        self.messages = [message(20,7)]
        self.downloader.cancelled = True
        self.downloader.paused = False
        status = await self.downloader.download(
            self.channel,self.folder,'all','all',2,False,
            lambda *a:None,self.logs.append,lambda *a:None,
            topic_id=7,reset_controls=False)
        self.assertEqual(status,'cancelled')
        self.messages[0].download_media.assert_not_awaited()
        self.assertEqual(self.checkpoint(),0)

    async def test_cancel_while_paused(self):
        self.messages = [message(20,7)]
        original = self.downloader.client.iter_messages
        async def iterate(*args, **kwargs):
            self.downloader.paused = True
            async for item in original(*args, **kwargs):
                yield item
        self.downloader.client.iter_messages = iterate
        async def sleep(seconds):
            self.downloader.cancelled = True
        with patch.object(d.asyncio,'sleep',side_effect=sleep):
            self.assertEqual(await self.run_download(),'cancelled')
        self.messages[0].download_media.assert_not_awaited()
        self.assertEqual(self.checkpoint(),0)

    async def test_cancel_during_transfer_removes_partial(self):
        m = message(20,7)
        async def cancel(file):
            file.write(b'synthetic partial fixture')
            self.downloader.cancelled = True
            return file
        m.download_media.side_effect = cancel
        self.messages = [m]
        self.assertEqual(await self.run_download(),'cancelled')
        self.assertEqual(list(Path(self.folder).iterdir()),[])
        self.assertEqual(self.checkpoint(),0)

    async def test_cancel_during_retry_stops_retries(self):
        m = message(20,7)
        m.download_media.side_effect = OSError('synthetic')
        self.messages = [m]
        async def sleep(seconds):
            self.downloader.cancelled = True
        with patch.object(d.asyncio,'sleep',side_effect=sleep):
            self.assertEqual(await self.run_download(),'cancelled')
        self.assertEqual(m.download_media.await_count,1)

    async def test_invalid_topic_and_limit_rejected(self):
        for tid in (None,0,-1,'7'):
            with self.subTest(topic=tid), self.assertRaises(ValueError):
                await self.run_download(topic_id=tid)
        with self.assertRaises(ValueError):
            await self.run_download(mode='0')
        self.channel.entity.forum = False
        with self.assertRaises(ValueError):
            await self.run_download(topic_id=7)

    async def test_symlink_destination_rejected(self):
        Path(self.folder).mkdir()
        target = Path(self.temp.name,'untouched')
        target.write_bytes(b'synthetic original')
        Path(self.folder,'20.bin').symlink_to(target)
        self.messages = [message(20,7)]
        with self.assertRaises(ValueError):
            await self.run_download()
        self.assertEqual(target.read_bytes(),b'synthetic original')


class DiscoveryTest(unittest.IsolatedAsyncioTestCase):
    async def test_paginated_topics_general_duplicate_names_and_deleted(self):
        a,b,g = topic(7),topic(8),topic(1,'General')
        client = AsyncMock(side_effect=[
            NS(topics=[b,ForumTopicDeleted(id=99)],messages=[NS(id=b.top_message,date=2)]),
            NS(topics=[a,g],messages=[]), NS(topics=[],messages=[])])
        downloader = d.TelegramDownloader.__new__(d.TelegramDownloader)
        downloader.client = client
        self.assertEqual([t.id for t in await downloader.get_topics(NS(entity=object()))],[1,7,8])
        request = client.call_args_list[1].args[0]
        self.assertEqual((request.offset_topic,request.offset_id,request.offset_date),(8,108,2))

    async def test_discovery_error_propagates_without_bulk_fallback(self):
        downloader = d.TelegramDownloader.__new__(d.TelegramDownloader)
        downloader.client = AsyncMock(side_effect=RuntimeError('synthetic API failure'))
        with self.assertRaises(RuntimeError):
            await downloader.get_topics(NS(entity=object()))

    async def test_nonadvancing_pagination_fails(self):
        downloader = d.TelegramDownloader.__new__(d.TelegramDownloader)
        downloader.client = AsyncMock(return_value=NS(topics=[topic(7)],messages=[]))
        with self.assertRaises(RuntimeError):
            await downloader.get_topics(NS(entity=object()))
        self.assertEqual(downloader.client.await_count,2)

    async def test_empty_discovery(self):
        downloader = d.TelegramDownloader.__new__(d.TelegramDownloader)
        downloader.client = AsyncMock(return_value=NS(topics=[],messages=[]))
        self.assertEqual(await downloader.get_topics(NS(entity=object())),[])


class HelpersTest(unittest.TestCase):
    def test_media_filters(self):
        downloader = d.TelegramDownloader.__new__(d.TelegramDownloader)
        cases = [(message(1), 'photo', True), (message(1), '.jpg,.pdf', True),
                 (document(1,7,'REPORT.PDF','application/pdf'), '.pdf', True),
                 (document(1,7,'movie.mp4','video/mp4'), 'video', True),
                 (document(1,7,'song.ogg','audio/ogg'), 'audio', True),
                 (document(1,7,'movie.mp4','video/mp4'), '.pdf', False)]
        for m,filter_,expected in cases:
            self.assertEqual(downloader.matches_filter(m,filter_),expected)

    def test_direct_and_nested_topic_reply(self):
        m = message(10,7)
        self.assertTrue(d.message_in_topic(m,7))
        m.reply_to.reply_to_top_id = None
        m.reply_to.reply_to_msg_id = 7
        self.assertTrue(d.message_in_topic(m,7))
        self.assertFalse(d.message_in_topic(m,1))
        self.assertTrue(d.message_in_topic(m,None))

    def test_scope_includes_destination_topic_and_normalized_filter(self):
        self.assertEqual(d.sync_key(1,7,'.PDF, .zip'),d.sync_key(1,7,'.zip,.pdf'))
        self.assertNotEqual(d.sync_key(1,7),d.sync_key(1,8))
        self.assertNotEqual(d.sync_key(1,None,'photo'),d.sync_key(1,None,'video'))
        self.assertNotEqual(d.sync_key(1,7,folder='/tmp/a'),d.sync_key(1,7,folder='/tmp/b'))

    def test_safe_paths_and_filename(self):
        for title in ('..','../escape','/absolute','a\\b',''):
            folder = Path(d.group_folder('/tmp/base',title,1))
            self.assertEqual(folder.parent,Path('/tmp/base'))
        self.assertEqual(d.media_filename(message(2,extension='/../../bad')), '2.bin')

    def test_state_corruption_atomic_permissions_and_monotonicity(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(d,'SYNC_FILE',str(Path(folder,'state.json'))):
            Path(d.SYNC_FILE).write_text('{broken')
            self.assertEqual(d.load_last_id(1,7),0)
            d.save_last_id(1,20,7)
            d.save_last_id(1,10,7)
            self.assertEqual(d.load_last_id(1,7),20)
            self.assertEqual(os.stat(d.SYNC_FILE).st_mode & 0o777,0o600)
            self.assertFalse(list(Path(folder).glob('.local-state-*')))
            write_json(d.SYNC_FILE,[])
            self.assertEqual(read_json(d.SYNC_FILE,{}),{})

    def test_failed_state_write_preserves_previous_data(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder,'state.json')
            write_json(path, {'fixture':1})
            with patch('local_data.os.replace',side_effect=OSError('synthetic disk error')):
                with self.assertRaises(OSError):
                    write_json(path,{'fixture':2})
            self.assertEqual(read_json(path,{}),{'fixture':1})
            self.assertEqual(len(list(Path(folder).iterdir())),1)


if __name__ == '__main__':
    unittest.main()
