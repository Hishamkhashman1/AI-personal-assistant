from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from pathlib import Path
import shutil
import os


from app.summarizer import summarize_meeting
from app.memory import save_meeting, get_latest_meeting
from app.persona import build_persona_prompt
from app.transcriber import transcribe_audio
from app.task_queue import queue
from app.jobs import join_meeting_job
from app.calendar_client import get_upcoming_events, get_next_event_with_meet_link

from rq.job import Job
from app.task_queue import redis_conn


from openai import OpenAI


#initiate Fastapi app
app = FastAPI()

ai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

AUDIO_DIR = Path("audio_samples")
AUDIO_DIR.mkdir(exist_ok=True)

def process_meeting_transcript(title, transcript):
    path = save_meeting(title, transcript)
    summary = summarize_meeting(transcript)
    return {
        "saved_transcript_to": path,
        "analysis": summary,
    }

   

class MeetingInput(BaseModel):
    title: str
    transcript: str

class QuestionInput(BaseModel):
    question: str

class JoinMeeting(BaseModel):
    title: str
    meeting_url: str

def enqueue_meeting_job(title: str, meeting_url: str):
    job = queue.enqueue(
            join_meeting_job,
            meeting_url,
            title,
    )
    return {
        "job_id": job.id,
        "status": "queued",
    }

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

    meeting_result = process_meeting_transcript(title, transcript) 
    return {
        "saved_audio_to": str(audio_path),
        "transcript": transcript,
        **meeting_result
        }

@app.post("/meeting/join")
def join_meeting(data: JoinMeeting):
    title = data.title.strip()
    meeting_url = data.meeting_url.strip()

    if not meeting_url:
        raise HTTPException(status_code=400, detail="meeting_url is required")

    return enqueue_meeting_job(title, meeting_url)

@app.get("/calendar/events")
def calendar_events():
    events = get_upcoming_events()
    return {
        "events": events,
    }

@app.post("/calendar/join-next")
def calendar_join_next():
    event = get_next_event_with_meet_link()

    if not event or not event.get("meeting_url"):
        raise HTTPException(
            status_code=404,
            detail="No upcoming calendar event with a Google Meet link found",
        )

    queue_result = enqueue_meeting_job(event["title"], event["meeting_url"])
    return {
        "title": event["title"],
        "meeting_url": event["meeting_url"],
        **queue_result,
    }

@app.get("/job/{job_id}")
def get_job_status(job_id: str):
    job = Job.fetch(job_id, connection=redis_conn)
    return {
        "job_id": job.id,
        "status": job.get_status(),
        "result": job.result,
        "meta": job.meta,
    }
@app.post("/meeting")
def process_meeting(data: MeetingInput):
    return process_meeting_transcript(data.title, data.transcript)

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
