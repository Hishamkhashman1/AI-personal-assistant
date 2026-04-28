import argparse
import subprocess
from pathlib import Path


CHROME_BINARY = "/usr/bin/google-chrome"
PROFILE_DIR = Path("browser_profiles/bot").resolve()
REMOTE_DEBUGGING_PORT = "9222"
GENERATED_DIR = Path("data/generated_camera")
DEFAULT_VIDEO_FILE = Path("assets/avatar_loop_slow.mp4")


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


def _convert_video_to_y4m(video_path: Path) -> Path:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    y4m_path = GENERATED_DIR / f"{video_path.stem}.y4m"

    if y4m_path.exists() and y4m_path.stat().st_mtime >= video_path.stat().st_mtime:
        return y4m_path

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-an",
        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2,fps=30,format=yuv420p",
        "-f",
        "yuv4mpegpipe",
        str(y4m_path),
    ]
    subprocess.run(cmd, check=True)
    return y4m_path


def launch_chrome(video_file: Path | None = DEFAULT_VIDEO_FILE, open_url: str = "https://meet.google.com"):
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
        open_url,
    ]

    if video_file:
        resolved_video = video_file.expanduser().resolve()
        if not resolved_video.is_file():
            raise FileNotFoundError(f"Video file not found: {resolved_video}")

        if resolved_video.suffix.lower() == ".y4m":
            y4m_file = resolved_video
        else:
            y4m_file = _convert_video_to_y4m(resolved_video)

        cmd.extend(
            [
                "--use-fake-device-for-media-stream",
                f"--use-file-for-fake-video-capture={y4m_file}",
                "--use-fake-ui-for-media-stream",
            ]
        )

    return subprocess.Popen(cmd, start_new_session=True)


def main():
    parser = argparse.ArgumentParser(description="Launch Chrome for the meeting bot.")
    parser.add_argument(
        "--video-file",
        type=Path,
        default=DEFAULT_VIDEO_FILE,
        help="Optional mp4/mkv/mov file to feed Chrome as a fake camera.",
    )
    parser.add_argument(
        "--open-url",
        default="https://meet.google.com",
        help="URL to open after Chrome launches.",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Launch Chrome and return immediately instead of waiting for Enter.",
    )
    args = parser.parse_args()

    proc = launch_chrome(video_file=args.video_file, open_url=args.open_url)

    print("Launching Chrome with the bot profile.")
    if args.video_file:
        print(f"Using fake camera video: {args.video_file.expanduser().resolve()}")

    if args.no_wait:
        return 0

    print("Keep this window open while the worker runs.")
    print("Press Enter here when you want to close Chrome.")

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
