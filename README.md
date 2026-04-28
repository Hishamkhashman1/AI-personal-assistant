# AI Personal Assistant

## Local run

1. Start Redis:
```bash
redis-server
```

2. Start the API:
```bash
uvicorn app.main:app --reload
```

3. Start the RQ worker:
```bash
python worker.py
```

4. Open the bot Chrome profile for manual sign-in:
```bash
python launch_bot_chrome.py
```
Keep that Chrome window open while `python worker.py` runs.

If you want Chrome to use a loop video as the bot camera:
```bash
python launch_bot_chrome.py --video-file /path/to/your-loop.mp4
```
That converts the video to a Chrome fake-camera feed automatically.

## Calendar and Meet flow

- `GET /calendar/events`
- `POST /calendar/join-next`
- `POST /meeting/join`

## Queue flow

- `POST /meeting/join` enqueues a Meet job from a JSON body:
```json
{
  "title": "Team sync",
  "meeting_url": "https://meet.google.com/..."
}
```
