import os
import re
from dataclasses import dataclass, field
from typing import Iterable

from dotenv import load_dotenv
from openai import OpenAI

from app.memory import save_meeting
from app.persona import build_persona_prompt
from app.summarizer import summarize_meeting


load_dotenv()

_AI_CLIENT: OpenAI | None = None


NOISE_PATTERNS = [
    r"^meet$",
    r"^google meet$",
    r"^leave call$",
    r"^leave meeting$",
    r"^end meeting for all$",
    r"^people$",
    r"^meeting details$",
    r"^chat with everyone$",
    r"^audio settings$",
    r"^video settings$",
    r"^share screen$",
    r"^send a reaction$",
    r"^raise hand$",
    r"^more options$",
    r"^contributors\s+\d+$",
    r"^in the meeting$",
    r"^waiting to join$",
    r"^turn on captions$",
    r"^turn off captions$",
    r"^allow notifications$",
    r"^not now$",
    r"^learn more$",
    r"^support$",
    r"^feedback$",
    r"^report a problem$",
    r"^search$",
    r"^close$",
    r"^now$",
    r"^meetings$",
    r"^calls$",
    r"^video calls and meetings for everyone$",
    r"^connect, collaborate, and celebrate from anywhere with google meet$",
]


QUESTION_HINTS = [
    r"\?$",
    r"\bcan you\b",
    r"\bcould you\b",
    r"\bwould you\b",
    r"\bwhat is\b",
    r"\bwhat's\b",
    r"\bwhy\b",
    r"\bhow\b",
    r"\bwhen\b",
    r"\bwhere\b",
    r"\bwho\b",
]


def _client() -> OpenAI:
    global _AI_CLIENT
    if _AI_CLIENT is None:
        _AI_CLIENT = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _AI_CLIENT


def _normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip())


def _is_noise_line(line: str) -> bool:
    low = line.lower()
    if len(low) < 3:
        return True

    for pattern in NOISE_PATTERNS:
        if re.search(pattern, low, re.I):
            return True

    if re.fullmatch(r"[0-9:\sAPMapm.]+", line):
        return True

    return False


def _looks_like_question(line: str) -> bool:
    low = line.lower()
    for pattern in QUESTION_HINTS:
        if re.search(pattern, low, re.I):
            return True

    return False


def _iter_unique_lines(text: str) -> Iterable[str]:
    for raw_line in text.splitlines():
        line = _normalize_line(raw_line)
        if not line or _is_noise_line(line):
            continue
        yield line


@dataclass
class MeetingAISession:
    title: str
    transcript_lines: list[str] = field(default_factory=list)
    seen_lines: set[str] = field(default_factory=set)
    answered_questions: set[str] = field(default_factory=set)
    assistant_messages_sent: bool = False
    transcript_saved: bool = False

    def ingest_text(self, text: str) -> list[str]:
        new_lines: list[str] = []
        for line in _iter_unique_lines(text):
            if line in self.seen_lines:
                continue
            self.seen_lines.add(line)
            self.transcript_lines.append(line)
            new_lines.append(line)
        return new_lines

    def mark_own_message(self, message: str) -> None:
        normalized = _normalize_line(message)
        if normalized:
            self.seen_lines.add(normalized)

    def transcript(self) -> str:
        return "\n".join(self.transcript_lines).strip()

    def should_answer(self, line: str) -> bool:
        if line in self.answered_questions:
            return False
        return _looks_like_question(line)

    def mark_answered(self, line: str) -> None:
        self.answered_questions.add(line)

    def generate_answer(self, question: str) -> str:
        context = self.transcript()
        prompt = build_persona_prompt(context, question)
        response = _client().chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
        )
        return response.choices[0].message.content.strip()

    def finalize(self):
        transcript = self.transcript()
        if not transcript:
            return None

        transcript_path = save_meeting(self.title, transcript)
        summary = summarize_meeting(transcript)
        self.transcript_saved = True
        return {
            "transcript": transcript,
            "transcript_path": transcript_path,
            "summary": summary,
        }
