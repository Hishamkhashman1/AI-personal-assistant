# AI Personal Assistant

Local-first meeting assistant for Google Meet. It can:

- join meetings from a Google Calendar account
- capture meeting audio and transcribe it
- summarize the transcript
- optionally send follow-up reports through `ntfy` or email

## What is kept local

These files and folders are intentionally ignored and should not be committed:

- `.env`
- `credentials.json`
- `token.json`
- `browser_profiles/`
- `data/`

Use the included `.env.example` as the starting point for your own setup.

## Requirements

- Python 3.12 or newer
- Redis
- `ffmpeg`
- Google Chrome or Chromium
- Playwright Chromium (`playwright install chromium`)
- `python-multipart` is included in the Python dependencies for upload handling
- A Google Calendar OAuth client secret JSON file
- An OpenAI API key

## Setup

1. Create and activate a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

3. Install the browser runtime used by Playwright:
```bash
playwright install chromium
```

4. Copy the example environment file and fill in your values:
```bash
cp .env.example .env
```

5. Set at least these values in `.env`:
- `OPENAI_API_KEY`
- `MEETING_OWNER_NAME`
- `MEETING_OWNER_ALIASES` as a comma-separated list of the names or nicknames you are called in meetings
- `GOOGLE_OAUTH_CLIENT_SECRETS`

6. Put your Google OAuth client secret JSON where `GOOGLE_OAUTH_CLIENT_SECRETS` points, or leave the default `credentials.json` path.

7. Start Redis, then launch the full stack:
```bash
python start_bot.py
```

The launcher will:

- start Redis if it is not already running
- start the FastAPI app
- start the RQ worker
- start Chrome with the bundled fake-camera video
- list your upcoming Meet-linked calendar events
- let you choose which one to join

## Running pieces separately

Launch only Chrome:

```bash
python launch_bot_chrome.py
```

Use a different loop video:

```bash
python launch_bot_chrome.py --video-file /path/to/your-loop.mp4
```

Run the API:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Run the worker:

```bash
python worker.py
```

## Optional Integrations

### Email

Set `MEETING_REPORT_EMAIL`, `SMTP_HOST`, and the related SMTP fields to send meeting reports by email.

### ntfy

Set `NTFY_TOPIC` and `NTFY_SERVER` to publish summaries and transcripts to your own ntfy topic.

## API Endpoints

- `GET /calendar/events`
- `POST /calendar/join-next`
- `POST /meeting/join`
- `POST /meeting/audio`
- `POST /meeting`
- `POST /ask`
- `GET /job/{job_id}`

## Notes

- The calendar flow expects a valid Google OAuth token, which is stored in `token.json` locally after the first sign-in.
- The Meet bot uses `MEETING_ASSISTANT_NAME` as its display name in the browser.
- If you want the question-answering flow to recognize your name in transcripts, add your meeting aliases to `MEETING_OWNER_ALIASES`.
