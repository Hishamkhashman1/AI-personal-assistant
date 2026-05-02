from app.settings import get_openai_client


ai_client = get_openai_client()

def summarize_meeting(transcript: str):
    prompt = f"""
You are a sharp meeting assistant.

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
