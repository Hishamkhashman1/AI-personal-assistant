import subprocess
from pathlib import Path


CHROME_BINARY = "/usr/bin/google-chrome"
PROFILE_DIR = Path("browser_profiles/bot").resolve()
REMOTE_DEBUGGING_PORT = "9222"


def _clear_stale_profile_locks(profile_dir: Path):
    for relative_path in [
        "Default/LOCK",
        "SingletonLock",
        "SingletonCookie",
        "SingletonSocket",
    ]:
        lock_path = profile_dir / relative_path
        if lock_path.exists() or lock_path.is_symlink():
            try:
                lock_path.unlink()
            except OSError:
                pass


def main():
    _clear_stale_profile_locks(PROFILE_DIR)

    cmd = [
        CHROME_BINARY,
        f"--user-data-dir={PROFILE_DIR}",
        "--profile-directory=Default",
        f"--remote-debugging-port={REMOTE_DEBUGGING_PORT}",
        "--remote-debugging-address=127.0.0.1",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        "https://meet.google.com",
    ]

    print("Launching Chrome with the bot profile.")
    print("Keep this window open while the worker runs.")
    print("Press Enter here when you want to close Chrome.")

    proc = subprocess.Popen(cmd)
    try:
        input()
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
