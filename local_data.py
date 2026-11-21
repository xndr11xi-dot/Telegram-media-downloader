"""Local JSON state, with atomic replacement and private file permissions."""
import json
import os
import tempfile


def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as stream:
            data = json.load(stream)
        return data if isinstance(data, type(default)) else default
    except (FileNotFoundError, json.JSONDecodeError):
        # Corrupt checkpoints cause a safe rescan, never a skipped download.
        return default


def write_json(path, data):
    directory = os.path.dirname(os.path.abspath(path))
    fd, temporary = tempfile.mkstemp(prefix=".local-state-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


CONNECTION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               ".telegram-downloader", "credentials.json")


def load_connection_details():
    directory = os.path.dirname(CONNECTION_FILE)
    if os.path.islink(directory) or os.path.islink(CONNECTION_FILE):
        raise ValueError("Connection details must not use symbolic links")
    data = read_json(CONNECTION_FILE, {})
    keys = ("api_id", "api_hash", "phone")
    if not all(isinstance(data.get(key), str) and data[key].strip() for key in keys):
        return None
    if not data["api_id"].isdecimal() or int(data["api_id"]) <= 0:
        return None
    return {key: data[key] for key in keys}


def save_connection_details(api_id, api_hash, phone):
    directory = os.path.dirname(CONNECTION_FILE)
    if os.path.islink(directory) or os.path.islink(CONNECTION_FILE):
        raise ValueError("Connection details must not use symbolic links")
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    write_json(CONNECTION_FILE, {"api_id": api_id, "api_hash": api_hash, "phone": phone})


def forget_connection_details():
    if os.path.islink(os.path.dirname(CONNECTION_FILE)):
        raise ValueError("Connection directory must not be a symbolic link")
    try:
        os.unlink(CONNECTION_FILE)
    except FileNotFoundError:
        pass
