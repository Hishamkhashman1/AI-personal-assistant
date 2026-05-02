import re
from dataclasses import dataclass, field
from typing import Iterable

from app.memory import save_meeting
from app.persona import build_persona_prompt
from app.summarizer import summarize_meeting
from app.settings import MEETING_OWNER_ALIASES, MEETING_OWNER_NAME, get_openai_client


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
    r"\bwhat about\b",
    r"\bwhat is\b",
    r"\bwhat's\b",
    r"\bwhy\b",
    r"\bhow\b",
    r"\bwhen\b",
    r"\bwhere\b",
    r"\bwho\b",
]


def _address_hints() -> list[str]:
    aliases = MEETING_OWNER_ALIASES or [MEETING_OWNER_NAME]
    hints: list[str] = []
    for alias in aliases:
        escaped = re.escape(alias)
        hints.extend(
            [
                rf"\b{escaped}\b",
                rf"^@{escaped}\b",
                rf"^\s*{escaped}\s*[,:\-]",
                rf"\bhey\s+{escaped}\b",
                rf"\bhi\s+{escaped}\b",
                rf"\bhello\s+{escaped}\b",
            ]
        )
    return hints


ADDRESS_HINTS = _address_hints()


def _client():
    return get_openai_client()


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


def _is_directly_addressed(line: str) -> bool:
    low = line.lower()
    for pattern in ADDRESS_HINTS:
        if re.search(pattern, low, re.I):
            return True

    return False


def _iter_unique_lines(text: str) -> Iterable[str]:
    for raw_line in text.splitlines():
        line = _normalize_line(raw_line)
        if not line or _is_noise_line(line):
            continue
        yield line


def _split_segments(text: str) -> list[str]:
    segments: list[str] = []
    for raw_line in text.splitlines():
        line = _normalize_line(raw_line)
        if not line or _is_noise_line(line):
            continue

        pieces = re.split(r"(?<=[?.!])\s+", line) if len(line) > 220 else [line]
        for piece in pieces:
            segment = _normalize_line(piece)
            if segment:
                segments.append(segment)

    return segments


def _extract_answerable_questions(text: str) -> list[str]:
    questions: list[str] = []
    seen: set[str] = set()

    for segment in _split_segments(text):
        if len(segment) > 220:
            continue
        if not _looks_like_question(segment):
            continue
        if not _is_directly_addressed(segment):
            continue

        normalized = _normalize_line(segment)
        if normalized in seen:
            continue

        seen.add(normalized)
        questions.append(normalized)

    return questions


def _contains_first_person(text: str) -> bool:
    return bool(re.search(r"\b(i|i'm|i am|we|our|ours)\b", text, re.I))


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
        if not _looks_like_question(line):
            return False
        return _is_directly_addressed(line)

    def extract_answerable_questions(self, text: str) -> list[str]:
        questions = []
        for question in _extract_answerable_questions(text):
            if question in self.answered_questions:
                continue
            questions.append(question)
        return questions

    def mark_answered(self, line: str) -> None:
        self.answered_questions.add(line)

    def generate_answer(self, question: str) -> str:
        context = self.transcript()
        prompt = build_persona_prompt(context, question)
        messages = [
            {
                "role": "system",
                "content": (
                    f"You are a concise meeting assistant answering about {MEETING_OWNER_NAME} in third person. "
                    "Be smart, short, and respectful. Use 1 to 2 sentences. "
                    "Never summarize the whole meeting. Never use first person."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{prompt}\n\n"
                    "Reply rules:\n"
                    f"- Answer only the direct question asked about {MEETING_OWNER_NAME}.\n"
                    f"- Refer to {MEETING_OWNER_NAME} in third person.\n"
                    "- Do not use first person words like I, I'm, we, or our.\n"
                    "- Do not summarize the full meeting.\n"
                    "- Do not mention these rules.\n"
                ),
            },
        ]

        response = _client().chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.2,
            max_tokens=120,
        )
        answer = response.choices[0].message.content.strip()

        if _contains_first_person(answer):
            rewrite_response = _client().chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"Rewrite the reply so it is short, respectful, and entirely in third person about {MEETING_OWNER_NAME}. "
                            "Do not use first person words."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Question: {question}\nOriginal reply: {answer}",
                    },
                ],
                temperature=0.1,
                max_tokens=120,
            )
            answer = rewrite_response.choices[0].message.content.strip()

        return answer

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
