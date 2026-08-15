import time
import requests
import json
from app.config import settings

def run_simulation(webhook_url: str, count: int = 500, duration_seconds: int = 10):
    print("=" * 60)
    print(f"Starting Simulation Run on Pseudogram API")
    print(f"Webhook URL: {webhook_url}")
    print(f"Events Count: {count}")
    print(f"Duration: {duration_seconds} seconds")
    print("=" * 60)

    url = f"{settings.PSEUDOGRAM_BASE_URL}/v1/simulate/start"
    headers = {
        "X-API-Key": settings.API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "webhook_url": webhook_url,
        "count": count,
        "duration_seconds": duration_seconds
    }

    resp = requests.post(url, json=payload, headers=headers)
    print(f"Start Simulation HTTP Status: {resp.status_code}")
    print(f"Response: {resp.text}")

    if resp.status_code != 200:
        print("Failed to start simulation.")
        return

    run_id = resp.json().get("run_id")
    print(f"Simulation Run ID: {run_id}")

    print("\nWaiting for simulation events to process...")
    # Wait for initial event delivery window plus worker processing time
    time.sleep(duration_seconds + 5)

    truth_url = f"{settings.PSEUDOGRAM_BASE_URL}/v1/simulate/{run_id}/truth"
    print(f"\nFetching ground truth from: {truth_url}")
    
    truth_resp = requests.get(truth_url, headers=headers)
    print(f"Truth HTTP Status: {truth_resp.status_code}")
    if truth_resp.status_code == 200:
        print("Server Ground Truth:")
        print(json.dumps(truth_resp.json(), indent=2))

    print("\nSimulation check completed.")

if __name__ == "__main__":
    import sys
    url = sys.argv[1] if len(sys.argv) > 1 else settings.WORKING_URL + "/webhook"
    run_simulation(url)
