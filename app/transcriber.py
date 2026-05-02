from app.settings import BASE_DIR, get_openai_client


ai_client = get_openai_client()
AUDIO_DIR = BASE_DIR / "audio_samples"


def transcribe_audio(audio_filename: str) -> str:
    audio_path = AUDIO_DIR / audio_filename

    if not audio_path.is_file():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    with audio_path.open("rb") as audio_file:
        transcript = ai_client.audio.transcriptions.create(
            model="gpt-4o-mini-transcribe",
            file=audio_file,
        )

    return transcript.text
