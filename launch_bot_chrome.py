import argparse
import subprocess
from pathlib import Path


CHROME_BINARY = "/usr/bin/google-chrome"
PROFILE_DIR = Path("browser_profiles/bot").resolve()
REMOTE_DEBUGGING_PORT = "9222"
GENERATED_DIR = Path("data/generated_camera")


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


def main():
    parser = argparse.ArgumentParser(description="Launch Chrome for the meeting bot.")
    parser.add_argument(
        "--video-file",
        type=Path,
        help="Optional mp4/mkv/mov file to feed Chrome as a fake camera.",
    )
    parser.add_argument(
        "--open-url",
        default="https://meet.google.com",
        help="URL to open after Chrome launches.",
    )
    args = parser.parse_args()

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
        args.open_url,
    ]

    if args.video_file:
        video_file = args.video_file.expanduser().resolve()
        if not video_file.is_file():
            raise FileNotFoundError(f"Video file not found: {video_file}")

        if video_file.suffix.lower() == ".y4m":
            y4m_file = video_file
        else:
            y4m_file = _convert_video_to_y4m(video_file)

        cmd.extend(
            [
                "--use-fake-device-for-media-stream",
                f"--use-file-for-fake-video-capture={y4m_file}",
                "--use-fake-ui-for-media-stream",
            ]
        )

    print("Launching Chrome with the bot profile.")
    if args.video_file:
        print(f"Using fake camera video: {args.video_file}")
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
