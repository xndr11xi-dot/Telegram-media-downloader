"""Synthetic selection and multi-job regression coverage; no Telegram login."""
import asyncio
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import test_app
from test_app import Widget
from app import App
from test_topics import document, message
from downloader import TelegramDownloader, sync_key


class SelectionTest(test_app.AppTest):
    async def test_search_keeps_hidden_topic_selected(self):
        self.app.topics = {'Photos [7]': 7, 'Clips [8]': 8}
        self.app.topic_checks = {name: (Widget(True), Widget()) for name in self.app.topics}
        self.app.topic_search.set('photos')
        App.filter_topics(self.app)
        self.assertFalse(self.app.topic_checks['Clips [8]'][1].options['visible'])
        self.assertTrue(self.app.topic_checks['Clips [8]'][0].get())
        App.select_topics(self.app, False)
        self.assertFalse(any(v.get() for v, _ in self.app.topic_checks.values()))

    async def test_channel_search_no_match_does_not_change_selected_channel(self):
        selected = self.app.channel_var.get()
        self.app.channel_search.set('absent')
        App.filter_channels(self.app)
        self.assertEqual(self.app.channel_var.get(), selected)
        self.assertEqual(self.app.channel_menu.options['state'], 'disabled')

    async def test_multi_topic_job_uses_separate_folders_and_combined_filters(self):
        self.app.topics = {'Photos [7]': 7, 'Clips [8]': 8}
        self.app.topic_checks = {name: (Widget(True), Widget()) for name in self.app.topics}
        self.app.all_media.set(False)
        self.app.media_checks['photo'].set(True)
        self.app.media_checks['video'].set(True)
        for name, value in [('limit_mode', 'custom'), ('custom_limit', '2'), ('folder_path', '/synthetic-destination'), ('reverse', False)]:
            setattr(self.app, name, Widget(value))
        self.app._load_history_tab = lambda: None
        self.app.downloader.download = AsyncMock(return_value='complete')
        App.start_download(self.app)
        await asyncio.gather(*self.tasks)
        calls = self.app.downloader.download.await_args_list
        self.assertEqual([c.kwargs['topic_id'] for c in calls], [7, 8])
        self.assertTrue(calls[0].args[1].endswith('/topic_7'))
        self.assertTrue(calls[1].args[1].endswith('/topic_8'))
        self.assertTrue(all(c.args[2] == 'photo,video' for c in calls))

    async def test_cancel_stops_before_next_topic(self):
        self.app.topics = {'A [7]': 7, 'B [8]': 8}
        self.app.topic_checks = {name: (Widget(True), Widget()) for name in self.app.topics}
        for name, value in [('limit_mode', 'all'), ('custom_limit', ''), ('folder_path', '/synthetic-destination'), ('reverse', False)]:
            setattr(self.app, name, Widget(value))
        async def cancel(*args, **kwargs):
            self.app.downloader.cancelled = True
            return 'cancelled'
        self.app.downloader.download = AsyncMock(side_effect=cancel)
        App.start_download(self.app)
        await asyncio.gather(*self.tasks)
        self.app.downloader.download.assert_awaited_once()
        self.assertFalse(self.app.busy)

    async def test_empty_media_and_invalid_limit_never_schedule(self):
        self.app.topics = {'A [7]': 7}
        self.app.topic_checks = {'A [7]': (Widget(True), Widget())}
        self.app.all_media.set(False)
        App.start_download(self.app)
        self.assertEqual(self.tasks, [])
        self.app.all_media.set(True)
        self.app.limit_mode = Widget('custom')
        self.app.custom_limit = Widget('0')
        App.start_download(self.app)
        self.assertEqual(self.tasks, [])


class CombinedFilterTest(unittest.TestCase):
    def test_or_filters_accept_both_types_and_reject_other_documents(self):
        downloader = TelegramDownloader.__new__(TelegramDownloader)
        self.assertTrue(downloader.matches_filter(message(1), 'photo,video'))
        self.assertTrue(downloader.matches_filter(document(2, 7, 'clip.mp4', 'video/mp4'), 'photo,video'))
        self.assertFalse(downloader.matches_filter(document(3, 7, 'text.pdf', 'application/pdf'), 'photo,video'))
        self.assertTrue(downloader.matches_filter(document(3, 7, 'text.pdf', 'application/pdf'), 'photo,.pdf'))

    def test_filter_order_has_same_checkpoint_but_topics_are_independent(self):
        self.assertEqual(sync_key(1, 7, 'photo,video'), sync_key(1, 7, 'video,photo'))
        self.assertNotEqual(sync_key(1, 7, 'photo,video'), sync_key(1, 8, 'photo,video'))
