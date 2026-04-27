from playwright.sync_api import sync_playwright

def join_meeting_job(meeting_url: str, title: str):
    print(f"Job Started for: {title}")
    print(f"Meeting URL:{meeting_url}")
    browser = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                    headless=False,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            page = browser.new_page()

            page.goto(meeting_url, wait_until="domcontentloaded", timeout=60_000)
            print("Page opened successfully")

            page.wait_for_timeout(10_000)

            print(f"Browser session finished for {title}")
    finally:
       if browser:
        browser.close()

    return {
        "title": title,
        "meeting_url": meeting_url,
        "status": "browser_opened_and_closed",
    }

