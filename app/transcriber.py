#imports



#input variable input = "audio file path"


#output output = transcript text (data/meetings/meetingtitledate.text not here just as a refference to where it will actually go)

# funciton def trasncribe_audio  with the following actions:
# 1 open audio file

# 2 send to AI

# 3 return transcript

from pathlib import Path
import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
ai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

BASE_DIR = Path(__file__).resolve().parents[1]
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
    #print(transcript.text) # for testing remove later
    return transcript.text

# just for testing remove later

#transcribe_audio("test_sp.wav")
