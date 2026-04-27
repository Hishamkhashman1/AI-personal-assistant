from playwright.sync_api import sync_playwright

def join_meeting_job(meeting_url: str, title: str):
    print(f"Job Started for: {title}")
    print(f"Meeting URL:{meeting_url}")
    browser = None
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
                ],
            )   
        try:
            context = browser.new_context(
                    locale="en-us",
                    permissions=["camera","microphone"]
            )
            page = context.new_page()
            if "?" in meeting_url:
                meeting_url += "&hl=en"
            else:
                meeting_url += "?hl=en"
            page.goto(meeting_url, wait_until="domcontentloaded", timeout=(60_000))
            print("Page opened successfully")
            page.wait_for_timeout(3000)

            name_input = page.locator("input[type='text']")
            if name_input.count() > 0:
                name_input.first.fill("Hisham Jr.")

            join_button = page.locator("button:has-text('Join')")
            if join_button.count() > 0:
                join_button.first.click()
            else:
                ask_button = page.locator("button:has-text('Ask')")
                if ask_button.count() > 0:
                    ask_button.first.click()
            page.wait_for_timeout(60000)

            print(f"Browser session finished for {title}")
        finally:
            if browser:
                browser.close()

    return {
        "title": title,
        "meeting_url": meeting_url,
        "status": "browser_opened_and_closed",
    }

