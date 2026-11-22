"""Private, bounded diagnostics without exception messages or user content."""
import asyncio
from concurrent.futures import CancelledError as FutureCancelledError
from datetime import datetime, timezone
import json
from importlib.metadata import version
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import threading
import traceback
import uuid

DIRECTORY = Path(__file__).resolve().parent / '.telegram-downloader' / 'diagnostics'
MAX_BYTES = 256 * 1024
BACKUP_COUNT = 3
SOURCE_FILES = {'app.py', 'downloader.py', 'main.py', 'local_data.py', 'history.py', 'diagnostics.py'}
EVENTS = {
    'application_started', 'application_closed', 'application_exit_incomplete',
    'application_failed', 'application_interrupted', 'unclean_exit_detected',
    'unexpected_mainloop_return', 'window_close_requested', 'closed_during_download',
    'unhandled_python_error', 'unhandled_thread_error', 'ui_callback_failed',
    'async_task_failed', 'background_task_failed', 'future_observer_failed',
    'preferences_read_failed', 'preferences_save_failed', 'credentials_read_failed',
    'credentials_save_failed', 'credentials_forget_failed', 'sync_reset_failed',
    'telegram_initialize_failed', 'login_failed', 'topic_load_failed',
    'sender_lookup_failed', 'download_failed', 'topic_folder_conflict',
    'discussion_checkpoint_save_failed', 'worker_failed', 'media_download_failed',
    'telegram_wait', 'discussion_load_failed', 'discussion_scope_mismatch',
    'local_json_invalid', 'local_json_wrong_type', 'download_started',
    'download_finished', 'download_paused', 'download_resumed', 'download_cancelled',
    'diagnostics_open_failed', 'diagnostic_state_failed', 'unclassified_issue',
}
_manager = None


def _private_directory(directory):
    if directory.parent.is_symlink():
        raise ValueError('Diagnostic directories must not use symbolic links')
    paths = (directory.parent, directory) if directory.parent.name == '.telegram-downloader' else (directory,)
    for path in paths:
        if path.is_symlink():
            raise ValueError('Diagnostic directories must not use symbolic links')
        path.mkdir(mode=0o700, exist_ok=True)
        if not path.is_dir():
            raise ValueError('Invalid diagnostic directory')
        path.chmod(0o700)


def _private_open(path, flags):
    if Path(path).is_symlink():
        raise ValueError('Diagnostic files must not use symbolic links')
    fd = os.open(path, flags | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0), 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Invalid diagnostic file')
        if hasattr(os, 'fchmod'):
            os.fchmod(fd, 0o600)
        else:
            os.chmod(path, 0o600)
        return fd
    except BaseException:
        os.close(fd)
        raise


class _PrivateHandler(RotatingFileHandler):
    def _open(self):
        fd = _private_open(self.baseFilename, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        return os.fdopen(fd, 'a', encoding='utf-8')

    def handleError(self, record):
        # Logging must never emit a raw traceback/request to stderr or break the UI.
        self.failed = True


def _process_is_alive(pid):
    if type(pid) is not int or not 0 < pid < 2**31:
        return False
    if os.name == 'nt':
        # os.kill(pid, 0) is not a safe liveness probe on Windows.
        try:
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
            kernel.GetExitCodeProcess.restype = wintypes.BOOL
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            handle = kernel.OpenProcess(0x1000, False, pid)
            if not handle:
                return ctypes.get_last_error() != 87
            try:
                status = wintypes.DWORD()
                return not kernel.GetExitCodeProcess(handle, ctypes.byref(status)) or status.value == 259
            finally:
                kernel.CloseHandle(handle)
        except Exception:
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _safe_record(event, error=None, tb=None, **details):
    entry = {'event': event if isinstance(event, str) and event in EVENTS else 'unclassified_issue'}
    if isinstance(error, BaseException):
        name = type(error).__name__
        entry['exception'] = name if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,79}', name) else 'Exception'
        frames = []
        for frame, line in traceback.walk_tb(tb if tb is not None else error.__traceback__):
            name = Path(frame.f_code.co_filename).name
            if name in SOURCE_FILES:
                frames.append({'file': name, 'line': line})
        if frames:
            entry['frames'] = frames[-20:]
        if isinstance(error, OSError) and type(error.errno) is int and 0 < error.errno <= 4096:
            entry['errno'] = error.errno
    for key in ('downloaded', 'skipped', 'attempt', 'parallel_downloads', 'wait_seconds'):
        value = details.get(key)
        if type(value) is int and 0 <= value <= 2**31 - 1:
            entry[key] = value
    if type(details.get('active_job')) is bool:
        entry['active_job'] = details['active_job']
    if details.get('result') in ('complete', 'incomplete', 'cancelled', 'failed'):
        entry['result'] = details['result']
    return entry


class Diagnostics:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else DIRECTORY
        self.run_id = uuid.uuid4().hex
        self.marker = self.directory / f'run-{self.run_id}.json'
        self.previous_unclean = False
        self.enabled = False
        self.handler = None
        self._previous_sys = self._previous_thread = None
        self._sys_hook = self._thread_hook = None
        try:
            _private_directory(self.directory)
            # Reject pre-existing symlinks/hardlinks, including rotation backups.
            for suffix in ('', '.1', '.2', '.3'):
                path = self.directory / ('issues.log' + suffix)
                if path.exists() or path.is_symlink():
                    fd = _private_open(path, os.O_WRONLY | os.O_APPEND)
                    os.close(fd)
            self.handler = _PrivateHandler(self.directory / 'issues.log',
                maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding='utf-8')
            self.handler.failed = False
            self.handler.setFormatter(logging.Formatter('%(message)s'))
            self.logger = logging.Logger('telegram_downloader_diagnostics', level=logging.INFO)
            self.logger.propagate = False
            self.logger.addHandler(self.handler)
            self.enabled = True
            self._detect_previous_exit()
            temporary = self.marker.with_suffix('.tmp')
            try:
                fd = _private_open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
                with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                    json.dump({'pid': os.getpid()}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.marker)
            finally:
                temporary.unlink(missing_ok=True)
            self.record('application_started', level='INFO')
        except Exception:
            self.enabled = False
            if self.handler is not None:
                try:
                    self.handler.close()
                except Exception:
                    pass

    @property
    def available(self):
        return self.enabled and self.handler is not None and not self.handler.failed

    def _detect_previous_exit(self):
        for path in self.directory.glob('run-*.json'):
            if not re.fullmatch(r'run-[0-9a-f]{32}\.json', path.name):
                continue
            try:
                fd = _private_open(path, os.O_RDONLY)
                with os.fdopen(fd, 'r', encoding='utf-8') as stream:
                    data = json.loads(stream.read(4096))
                pid = data.get('pid') if isinstance(data, dict) else None
                if _process_is_alive(pid):
                    continue
                self.previous_unclean = True
                self.record('unclean_exit_detected', level='WARNING')
                path.unlink()
            except Exception as error:
                self.record('diagnostic_state_failed', error, level='WARNING')

    def record(self, event, error=None, *, level='ERROR', tb=None, **details):
        if not self.available:
            return
        try:
            entry = _safe_record(event, error, tb, **details)
            entry.update(time=datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                         level=level if level in ('INFO', 'WARNING', 'ERROR') else 'ERROR',
                         run=self.run_id, schema=1)
            if entry['event'] == 'application_started':
                entry['python'] = '.'.join(map(str, sys.version_info[:3]))
                system = platform.system()
                entry['system'] = system if system in ('Darwin', 'Linux', 'Windows') else 'Other'
                for package in ('Telethon', 'customtkinter'):
                    try:
                        installed = version(package)
                        if len(installed) <= 32 and re.fullmatch(r'\d+(?:\.\d+){1,3}(?:(?:a|b|rc)\d+)?', installed):
                            entry[package.lower()] = installed
                    except Exception:
                        pass
            self.logger.log(getattr(logging, entry['level']), json.dumps(entry, ensure_ascii=True))
            if entry['level'] == 'ERROR' and self.available:
                self.handler.flush()
                os.fsync(self.handler.stream.fileno())
        except Exception:
            self.enabled = False

    def install_hooks(self):
        self._previous_sys = sys.excepthook
        self._previous_thread = threading.excepthook
        def sys_hook(exc_type, error, tb):
            self.record('unhandled_python_error', error, tb=tb)
            try:
                sys.stderr.write('Unexpected error. Check the private diagnostic logs.\n')
            except Exception:
                pass
        def thread_hook(args):
            self.record('unhandled_thread_error', args.exc_value, tb=args.exc_traceback)
        self._sys_hook, self._thread_hook = sys_hook, thread_hook
        sys.excepthook, threading.excepthook = sys_hook, thread_hook

    def close(self, clean=True):
        self.record('application_closed' if clean else 'application_exit_incomplete',
                    level='INFO' if clean else 'ERROR')
        if clean:
            try:
                self.marker.unlink(missing_ok=True)
            except OSError as error:
                self.record('diagnostic_state_failed', error, level='WARNING')
        if self._sys_hook is not None and sys.excepthook is self._sys_hook:
            sys.excepthook = self._previous_sys
        if self._thread_hook is not None and threading.excepthook is self._thread_hook:
            threading.excepthook = self._previous_thread
        if self.handler is not None:
            try:
                self.handler.close()
            except Exception:
                pass
        self.enabled = False


def start_diagnostics(directory=None):
    global _manager
    if _manager is None:
        _manager = Diagnostics(directory)
        _manager.install_hooks()
    return _manager


def stop_diagnostics(clean=True):
    global _manager
    manager, _manager = _manager, None
    if manager is not None:
        manager.close(clean)


def record_issue(event, error=None, **details):
    if _manager is not None:
        _manager.record(event, error, **details)


def async_exception_handler(loop, context):
    record_issue('async_task_failed', context.get('exception'))


def observe_future(future):
    def completed(item):
        try:
            error = item.exception()
        except (asyncio.CancelledError, FutureCancelledError):
            return
        except Exception as error:
            record_issue('future_observer_failed', error)
            return
        if error is not None:
            record_issue('background_task_failed', error)
    future.add_done_callback(completed)
    return future


def open_diagnostics_folder():
    if _manager is None or not _manager.available:
        return False
    _private_directory(_manager.directory)
    directory = str(_manager.directory)
    if sys.platform == 'darwin':
        subprocess.Popen(['open', directory], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif os.name == 'nt':
        os.startfile(directory)
    else:
        subprocess.Popen(['xdg-open', directory], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True
