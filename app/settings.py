from functools import lru_cache
from pathlib import Path
import os

from dotenv import load_dotenv
from openai import OpenAI


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

DATA_DIR = BASE_DIR / "data"
MEETINGS_DIR = DATA_DIR / "meetings"
DEBUG_MEETINGS_DIR = DATA_DIR / "debug_meetings"
GENERATED_CAMERA_DIR = DATA_DIR / "generated_camera"
BROWSER_PROFILE_DIR = BASE_DIR / "browser_profiles" / "bot"

MEETING_ASSISTANT_NAME = os.getenv("MEETING_ASSISTANT_NAME", "Meeting Assistant").strip() or "Meeting Assistant"
MEETING_OWNER_NAME = os.getenv("MEETING_OWNER_NAME", "the user").strip() or "the user"
MEETING_OWNER_ALIASES = [
    alias.strip()
    for alias in os.getenv("MEETING_OWNER_ALIASES", "").split(",")
    if alias.strip()
]


def env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default

    try:
        return int(value)
    except ValueError:
        return default


@lru_cache
def get_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        return OpenAI(api_key=api_key)

    return OpenAI()
