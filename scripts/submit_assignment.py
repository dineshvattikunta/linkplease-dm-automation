import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import requests
import json
from app.config import settings

def submit():
    print("=" * 60)
    print("Submitting LinkPlease Tech Intern Assignment")
    print("=" * 60)

    url = f"{settings.PSEUDOGRAM_BASE_URL}/v1/submit"
    headers = {"Content-Type": "application/json"}
    
    payload = {
        "email": settings.USER_EMAIL,
        "github_repo": settings.GITHUB_REPO_URL,
        "working_url": settings.WORKING_URL,
        "loom_url": settings.LOOM_URL,
        "parts_completed": "A+B+C",
        "start_date": "2026-08-15"
    }

    print("Submission Payload:")
    print(json.dumps(payload, indent=2))
    
    confirm = input("\nDo you want to submit now? (y/N): ")
    if confirm.lower() == 'y':
        resp = requests.post(url, json=payload, headers=headers)
        print(f"HTTP Status: {resp.status_code}")
        print(f"Response: {resp.text}")
    else:
        print("Submission cancelled.")

if __name__ == "__main__":
    submit()
