import time 

def join_meeting_job(meeting_url: str, title: str):
    print(f"Job Started for: {title}")
    print(f"Meeting URL:{meeting_url}")

    time.sleep(10)

    print(f"Job for {title} Completed Succesfully")

    return {
        "title": title,
        "meeting_url": meeting_url,
        "status": "simulated_done"
    }

