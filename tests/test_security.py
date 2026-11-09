import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import downloader as d
from tools.audit_repository import content_findings


class SecurityTest(unittest.TestCase):
    def test_gitignore_blocks_local_data(self):
        samples = ['test.session', 'test.session-wal', '.env', '.env.production',
                   'config.local.toml', 'credentials.json', 'download_history.json',
                   'sync_state.json', '__pycache__/test.pyc', '.venv/bin/python',
                   'downloads/fixture.custom', 'group_-10042/fixture.custom',
                   'topic_7/fixture.custom', 'file.mp4', 'file.pdf', 'file.bin',
                   '.telegram-downloader/telegram.session', '.local-state-test.tmp']
        result = subprocess.run(['git','check-ignore','--no-index','--stdin'],
                                input='\n'.join(samples)+'\n',text=True,capture_output=True)
        self.assertEqual(result.returncode,0)
        self.assertEqual(set(result.stdout.splitlines()),set(samples))
        for source in ['app.py','requirements.txt','tests/test_topics.py']:
            result = subprocess.run(['git','check-ignore','--no-index',source],capture_output=True)
            self.assertEqual(result.returncode,1)

    def test_secret_scanner_reports_category_without_contents(self):
        fixture = ('api_hash = "' + 'a'*32 + '"').encode()
        self.assertIn('api-hash-literal',content_findings(fixture))
        self.assertEqual(content_findings(b'api_hash = "synthetic-fixture"'),[])

    def test_session_storage_is_private_and_phone_free(self):
        original = os.getcwd()
        with tempfile.TemporaryDirectory() as temporary:
            try:
                os.chdir(temporary)
                with patch.object(d,'TelegramClient') as client:
                    d.TelegramDownloader(1,'synthetic-api-hash','synthetic-phone')
                session = client.call_args.args[0]
                self.assertNotIn('synthetic-phone',session)
                self.assertEqual(Path(session).stat().st_mode & 0o777,0o600)
                self.assertEqual(Path(session).parent.stat().st_mode & 0o777,0o700)
                self.assertFalse(Path(session).read_bytes())
            finally:
                os.chdir(original)

    def test_symlink_session_directory_rejected(self):
        original = os.getcwd()
        with tempfile.TemporaryDirectory() as temporary:
            try:
                os.chdir(temporary)
                Path('target').mkdir()
                Path('.telegram-downloader').symlink_to('target',target_is_directory=True)
                with patch.object(d,'TelegramClient') as client, self.assertRaises(ValueError):
                    d.TelegramDownloader(1,'synthetic-api-hash','synthetic-phone')
                client.assert_not_called()
            finally:
                os.chdir(original)
