import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib import error, request

from redis import Redis

from launch_bot_chrome import DEFAULT_VIDEO_FILE, launch_chrome


API_URL = "http://127.0.0.1:8000"
REDIS_HOST = "localhost"
REDIS_PORT = 6379
CHROME_DEBUG_PORT = 9222


class ManagedProcess:
    def __init__(self, name: str, proc: subprocess.Popen, owned: bool = True):
        self.name = name
        self.proc = proc
        self.owned = owned

    def alive(self) -> bool:
        return self.proc.poll() is None

    def stop(self):
        if not self.alive():
            return

        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except Exception:
            try:
                self.proc.terminate()
            except Exception:
                pass

    def kill(self):
        if not self.alive():
            return

        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass


def _log(message: str):
    print(f"[boot] {message}", flush=True)


def _redis_ready() -> bool:
    try:
        return Redis(host=REDIS_HOST, port=REDIS_PORT, db=0).ping()
    except Exception:
        return False


def _wait_for_port(host: str, port: int, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            import socket

            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def _start_process(args: list[str], name: str) -> ManagedProcess:
    _log(f"starting {name}")
    proc = subprocess.Popen(args, start_new_session=True)
    return ManagedProcess(name, proc, owned=True)


def _ensure_redis() -> ManagedProcess | None:
    if _redis_ready():
        _log("redis already running")
        return None

    return _start_process(["redis-server"], "redis")


def _start_api() -> ManagedProcess:
    return _start_process(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        "api",
    )


def _start_worker() -> ManagedProcess:
    return _start_process([sys.executable, "worker.py"], "worker")


def _start_chrome(video_file: Path | None = DEFAULT_VIDEO_FILE) -> ManagedProcess:
    _log("starting chrome with the fake camera feed")
    proc = launch_chrome(video_file=video_file, open_url="https://meet.google.com")
    return ManagedProcess("chrome", proc, owned=True)


def _http_get_json(url: str):
    with request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_post_json(url: str, payload: dict):
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    with request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _calendar_events() -> list[dict]:
    payload = _http_get_json(f"{API_URL}/calendar/events")
    events = payload.get("events", [])
    return [event for event in events if event.get("meeting_url")]


def _pick_meeting(events: list[dict]) -> dict | None:
    if not events:
        return None

    print("\nUpcoming Meet-linked events:")
    for index, event in enumerate(events, start=1):
        print(
            f"{index}. {event.get('start', 'unknown time')} | {event.get('title', 'Untitled meeting')}"
        )
        print(f"   {event.get('meeting_url')}")

    while True:
        choice = input("\nPick a meeting number to join (or q to quit): ").strip().lower()
        if choice in {"q", "quit", "exit"}:
            return None

        try:
            index = int(choice)
        except ValueError:
            print("Enter a valid number from the list.")
            continue

        if 1 <= index <= len(events):
            return events[index - 1]

        print("That number is out of range.")


def _wait_for_api_ready(timeout: float = 60.0) -> bool:
    return _wait_for_port("127.0.0.1", 8000, timeout=timeout)


def _wait_for_chrome_debug(timeout: float = 60.0) -> bool:
    return _wait_for_port("127.0.0.1", CHROME_DEBUG_PORT, timeout=timeout)


def _cleanup(processes: list[ManagedProcess]):
    for process in reversed(processes):
        if process.owned:
            process.stop()
    time.sleep(2)
    for process in reversed(processes):
        if process.owned and process.alive():
            process.kill()


def main():
    processes: list[ManagedProcess] = []

    try:
        redis_proc = _ensure_redis()
        if redis_proc:
            processes.append(redis_proc)
            if not _wait_for_port(REDIS_HOST, REDIS_PORT, timeout=15):
                raise RuntimeError("Redis did not become ready")

        api_proc = _start_api()
        processes.append(api_proc)
        if not _wait_for_api_ready(timeout=60):
            raise RuntimeError("API did not become ready")

        worker_proc = _start_worker()
        processes.append(worker_proc)

        chrome_proc = _start_chrome(DEFAULT_VIDEO_FILE)
        processes.append(chrome_proc)
        if not _wait_for_chrome_debug(timeout=60):
            raise RuntimeError("Chrome debug port did not become ready")

        events = _calendar_events()
        if not events:
            _log("no upcoming Meet-linked events found")
            print("Press Ctrl-C to stop everything.")
            while True:
                time.sleep(60)

        selected = _pick_meeting(events)
        if not selected:
            _log("no meeting selected; keeping services running")
            print("Press Ctrl-C to stop everything.")
            while True:
                time.sleep(60)

        join_payload = {
            "title": selected.get("title", "Untitled meeting"),
            "meeting_url": selected["meeting_url"],
        }
        join_result = _http_post_json(f"{API_URL}/meeting/join", join_payload)
        print("\nQueued join job:")
        print(json.dumps(join_result, indent=2))

        job_id = join_result.get("job_id")
        if job_id:
            print("\nWaiting for the join job to finish...")
            while True:
                status = _http_get_json(f"{API_URL}/job/{job_id}")
                print(json.dumps(status, indent=2))
                if status.get("status") in {"finished", "failed"}:
                    break
                time.sleep(5)

        print("\nServices are still running. Press Ctrl-C to stop everything.")
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        _log("shutting down")
    finally:
        _cleanup(processes)


if __name__ == "__main__":
    main()
