from datetime import datetime
from local_data import read_json, write_json

HISTORY_FILE = "download_history.json"


def load_history():
    return read_json(HISTORY_FILE, [])


def save_history(channel_name, folder, count):
    history = load_history()
    history.append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "channel": channel_name,
        "folder": folder,
        "files": count,
    })
    write_json(HISTORY_FILE, history)
