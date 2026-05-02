from datetime import datetime
import os
import re

from app.settings import MEETINGS_DIR


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return slug or "meeting"

def save_meeting(title: str, transcript: str):
    os.makedirs(MEETINGS_DIR, exist_ok=True)
    filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_safe_slug(title)}.txt"
    path = os.path.join(MEETINGS_DIR, filename)

    with open(path, "w") as f:
        f.write(transcript)

    return path

def get_latest_meeting():
    files = sorted(os.listdir(MEETINGS_DIR))
    if not files:
        return None

    latest = files[-1]
    with open(os.path.join(MEETINGS_DIR, latest), "r") as f:
        return f.read()
