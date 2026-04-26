from fastapi import FastAPI
from pydantic import BaseModel
from app.summarizer import summarize_meeting
from app.memory import save_meeting, get_latest_meeting
from app.persona import build_persona_prompt
from openai import OpenAI
import os

app = FastAPI()

ai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class MeetingInput(BaseModel):
    title: str
    transcript: str

class QuestionInput(BaseModel):
    question: str

# Now define endpoints

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
        temprature=0.4,
    )

    return {
        "answer": response.choices[0].message.content
    }
