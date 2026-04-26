from fastapi import FastAPI, UploadFile, File, Form
from pydantic import BaseModel
from pathlib import Path
import shutil
import os


from app.summarizer import summarize_meeting
from app.memory import save_meeting, get_latest_meeting
from app.persona import build_persona_prompt
from app.transcriber import transcribe_audio
from openai import OpenAI


#initiate Fastapi app
app = FastAPI()

ai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

AUDIO_DIR = Path("audio_samples")
AUDIO_DIR.mkdir(exist_ok=True)

class MeetingInput(BaseModel):
    title: str
    transcript: str

class QuestionInput(BaseModel):
    question: str

# Now define endpoints
@app.post("/meeting/audio")
def process_audio_meeeting(
    title: str = Form(...),
    file: UploadFile = File(...)
):
    audio_path = AUDIO_DIR / file.filename

    with audio_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    transcript = transcribe_audio(file.filename)

    path = save_meeting(title, transcript)
    summary = summarize_meeting(transcript)

    return {
        "saved_audio_to": str(audio_path),
        "saved_transcript_to": path,
        "transcript": transcript,
        "analysis": summary,
        }

@app.post("/meeting")
def process_meeting(data: MeetingInput):
    path = save_meeting(data.title, data.transcript)
    summary = summarize_meeting(data.transcript)

    return {
            "saved_to": path,
            "analysis": summary
            }

@app.post("/ask")
def ask_question(data: QuestionInput):
    context = get_latest_meeting()
    if not context:
        return {"error": "No meeting actually found"}

    prompt = build_persona_prompt(context, data.question)

    response = ai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role":"user", "content": prompt}],
        temperature=0.4,
    )

    return {
        "answer": response.choices[0].message.content
    }
