from playwright.sync_api import sync_playwright

def join_meeting_job(meeting_url: str, title: str):
    print(f"Job Started for: {title}")
    print(f"Meeting URL:{meeting_url}")
    browser = None
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir="browser_profiles/bot",
            channel="chrome",
            headless=False,
            locale="en-US",
            permissions=["camera","microphone"],
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
                ],
            )   
        try:
            page = context.new_page()
            if "?" in meeting_url:
                meeting_url += "&hl=en"
            else:
                meeting_url += "?hl=en"
            page.goto(meeting_url, wait_until="domcontentloaded", timeout=(60_000))
            print("Page opened successfully")
            page.wait_for_timeout(3000)

            name_input = page.get_by_label("Your name")
            if name_input.count() > 0 and name_input.first.is_visible():
                name_input.first.fill("Hisham Jr.")

            join_button = page.get_by_role("button", name="Join now")
            if join_button.count() > 0:
                join_button.first.click()
            else:
                ask_button = page.get_by_role("button",name="Ask to join")
                if ask_button.count() > 0:
                    ask_button.first.click()
            page.wait_for_timeout(60000)

            print(f"Browser session finished for {title}")
        finally:
            if context:
                context.close()

    return {
        "title": title,
        "meeting_url": meeting_url,
        "status": "browser_opened_and_closed",
    }

