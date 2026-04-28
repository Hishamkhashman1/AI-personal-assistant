import os
from datetime import datetime
import re

BASE_PATH = "data/meetings"


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return slug or "meeting"

def save_meeting(title: str, transcript: str):
    os.makedirs(BASE_PATH,exist_ok=True)
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_safe_slug(title)}.txt"
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
        return f.read()
