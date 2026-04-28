# AI Personal Assistant

## Local run

1. Start everything in one command:
```bash
python start_bot.py
```

2. The launcher will:
   - start Redis
   - start the API
   - start the RQ worker
   - start Chrome with the bundled avatar loop video
   - list your upcoming Meet-linked calendar events
   - let you choose which one to join

If you want to launch Chrome by itself:
```bash
python launch_bot_chrome.py
```

If you want a different loop video:
```bash
python launch_bot_chrome.py --video-file /path/to/your-loop.mp4
```

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
