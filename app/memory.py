import os
from datetime import datetime

BASE_PATH = "data/meetings"

def save_meeting(title: str, transcript: str):
    os.makedirs(BASE_PATH,exist_ok=True)
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{title}.txt"
    path = os.path.join(BASE_PATH, filename)

    with open(path, "w") as f:
        f.write(transcript)

    return path

def get_latest_meeting():
    files = sorted(os.listdir(BASE_PATH))
    if not files:
        return None

    latest = files[-1]
    with open(os.path.join(BASE_PATH, latest), "r") as f:
        return f.read
