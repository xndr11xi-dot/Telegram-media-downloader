"""Headless GUI controller tests: no Tk window, session, credentials or network."""
import asyncio
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
try:
    from app import App
except ImportError:
    raise unittest.SkipTest('CustomTkinter/Tk imports unavailable in this interpreter')


class Widget:
    def __init__(self,value=''):
        self.value, self.options = value, {}
    def get(self):
        return self.value
    def set(self,value):
        self.value = value
    def configure(self,**options):
        self.options.update(options)
    def delete(self,*args):
        self.value = ''


def fake_app():
    app = NS(topics={},topic_generation=0,busy=False,channels=[],logs=[])
    for name in ['topic_var','channel_var','topic_menu','channel_menu','start_btn',
                 'pause_btn','cancel_btn','progress','progress_label','otp','otp_btn',
                 'api_hash','api_id','phone','login_btn']:
        setattr(app,name,Widget())
    app.after = lambda delay,func,*args:func(*args)
    app.log = app.logs.append
    app.selected_channel = lambda:App.selected_channel(app)
    app.downloader = NS(get_topics=AsyncMock(),paused=False,cancelled=False)
    app.loop = None
    return app


def channel(cid,forum=True):
    return NS(id=cid,name='Synthetic group',is_channel=True,entity=NS(forum=forum))


class AppTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.app = fake_app()
        self.tasks = []
        def schedule(coroutine,loop):
            task = asyncio.create_task(coroutine)
            self.tasks.append(task)
            return task
        self.schedule = patch('app.asyncio.run_coroutine_threadsafe',side_effect=schedule)
        self.schedule.start()
        self.addCleanup(self.schedule.stop)
        self.app.channels = [channel(-10042)]
        self.app.channel_var.set('📢 Synthetic group [-10042]')

    async def test_topic_selector_duplicate_titles_and_ids(self):
        self.app.downloader.get_topics.return_value = [NS(id=7,title='Files'),NS(id=8,title='Files')]
        App.select_channel(self.app)
        self.assertEqual(self.app.start_btn.options['state'],'disabled')
        await asyncio.gather(*self.tasks)
        self.assertEqual(self.app.topics,{'Files [7]':7,'Files [8]':8})
        self.assertEqual(self.app.start_btn.options['state'],'normal')

    async def test_topic_failure_never_enables_bulk_download_or_logs_exception(self):
        self.app.downloader.get_topics.side_effect = RuntimeError('SYNTHETIC_SECRET_MUST_NOT_APPEAR')
        App.select_channel(self.app)
        await asyncio.gather(*self.tasks)
        self.assertEqual(self.app.start_btn.options['state'],'disabled')
        self.assertEqual(self.app.topics,{})
        self.assertNotIn('SYNTHETIC_SECRET','\n'.join(self.app.logs))

    async def test_switching_to_normal_channel_discards_stale_response(self):
        gate = asyncio.Event()
        async def topics(_):
            await gate.wait()
            return [NS(id=7,title='Old topic')]
        self.app.downloader.get_topics.side_effect = topics
        App.select_channel(self.app)
        await asyncio.sleep(0)
        self.app.channels.append(channel(-10043,False))
        self.app.channel_var.set('📢 Synthetic group [-10043]')
        App.select_channel(self.app)
        gate.set()
        await asyncio.gather(*self.tasks)
        self.assertEqual(self.app.topics,{})
        self.assertEqual(self.app.topic_var.get(),'No topic required')
        self.assertEqual(self.app.start_btn.options['state'],'normal')

    async def test_pause_resume_cancel_prevents_second_job(self):
        App.pause(self.app)
        self.assertTrue(self.app.downloader.paused)
        App.pause(self.app)
        self.assertFalse(self.app.downloader.paused)
        self.app.busy = True
        App.cancel(self.app)
        self.assertTrue(self.app.downloader.cancelled)
        App.start_download(self.app)
        self.assertEqual(self.tasks,[])
        self.assertEqual(self.app.start_btn.options['state'],'disabled')

    async def test_download_error_restores_controls_and_hides_exception(self):
        for name,value in [('media_type','all'),('limit_mode','all'),('custom_limit','2'),
                           ('folder_path','/synthetic-destination'),('reverse',False)]:
            setattr(self.app,name,Widget(value))
        self.app.topics = {'Files [7]':7}
        self.app.topic_var.set('Files [7]')
        self.app.downloader.download = AsyncMock(side_effect=RuntimeError('SYNTHETIC_SECRET_MUST_NOT_APPEAR'))
        App.start_download(self.app)
        self.assertTrue(self.app.busy)
        await asyncio.gather(*self.tasks)
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.start_btn.options['state'],'normal')
        self.assertEqual(self.app.progress_label.options['text'],'Download failed')
        self.assertNotIn('SYNTHETIC_SECRET','\n'.join(self.app.logs))

    async def test_start_submits_selected_topic_and_recovers_for_next_download(self):
        for name, value in [('media_type','all'), ('limit_mode','custom'),
                            ('custom_limit','1'), ('folder_path','/synthetic-destination'),
                            ('reverse',False)]:
            setattr(self.app, name, Widget(value))
        self.app.topics = {'Files [7]': 7, 'Other [8]': 8}
        self.app.topic_var.set('Files [7]')
        self.app._load_history_tab = lambda: None
        async def download(*args, **kwargs):
            args[6](1, 0, 1.0)
            args[8](1, 0)
            return 'complete'
        self.app.downloader.download = AsyncMock(side_effect=download)
        with patch('app.save_history') as history:
            App.start_download(self.app)
            App.start_download(self.app)  # Duplicate clicks cannot start another job.
            await asyncio.gather(*self.tasks)
        call = self.app.downloader.download.call_args
        self.app.downloader.download.assert_awaited_once()
        self.assertEqual(call.kwargs, {'topic_id':7, 'reset_controls':False})
        self.assertTrue(call.args[1].endswith('/topic_7'))
        self.assertEqual(call.args[2:6], ('all','custom',1,False))
        history.assert_called_once()
        self.assertFalse(self.app.busy)
        self.assertEqual(self.app.progress_label.options['text'], 'Download complete')
        self.assertEqual(self.app.start_btn.options['state'], 'normal')

    async def test_login_error_does_not_log_exception(self):
        self.app.downloader.client = NS(connect=AsyncMock(side_effect=RuntimeError('SYNTHETIC_SECRET_MUST_NOT_APPEAR')))
        await App._async_login(self.app)
        self.assertNotIn('SYNTHETIC_SECRET','\n'.join(self.app.logs))

    async def test_otp_is_cleared_and_delivered_only_once(self):
        self.app.otp.set('synthetic-auth-code')
        self.app.loop = asyncio.get_running_loop()
        future = self.app.loop.create_future()
        self.app.downloader.otp_future = future
        App.submit_otp(self.app)
        await asyncio.sleep(0)
        self.assertEqual(self.app.otp.get(),'')
        self.assertEqual(future.result(),'synthetic-auth-code')
        self.assertNotIn('synthetic-auth-code','\n'.join(self.app.logs))
        self.app.otp.set('synthetic-second-code')
        App.submit_otp(self.app)
        await asyncio.sleep(0)
        self.assertEqual(future.result(),'synthetic-auth-code')
