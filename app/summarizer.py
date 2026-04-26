import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# the ai client
ai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def summarize_meeting(transcript: str):
    prompt = f"""
you are Hisham jr., a sharp meeting assistant.

Analyze the meeting transcript and return:

1. Summary(short)
2. Key Decisions
3. Action Items
4. Risks/ Concerns

Be concise and structured.

Transcript:
{transcript}
"""

    response = ai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
    )

    return response.choices[0].message.content
