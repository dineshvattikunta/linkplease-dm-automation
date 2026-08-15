import asyncio
import hmac
import hashlib
import json
import random
import time
import httpx
from app.config import settings

def generate_signature(body: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"

async def run_e2e_stress_test():
    base_url = "http://localhost:8000"
    
    print("=" * 60)
    print("STARTING DIRECT 500-EVENT E2E STRESS TEST & GROUND TRUTH AUDIT")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. Reset Database & Create Rule
        print("\n1. Setting up Rule: 'PRICE' -> 'Here is the price list: $99'")
        rule_resp = await client.post(f"{base_url}/rules", json={
            "keyword": "PRICE",
            "dm_message": "Here is the price list: $99"
        })
        print(f"Rule Response: {rule_resp.status_code} {rule_resp.text}")
        rule_data = rule_resp.json()
        rule_id = rule_data["rule_id"]

        # 2. Synthesize 500 Webhook Events with Realistic Edge Cases
        # - 50 unique users commenting "PRICE" (Expected 50 genuine sends)
        # - 250 duplicate comments by same users for same rule (Expected 250 user-rule duplicates blocked)
        # - 40 duplicate event_id redeliveries (Expected 40 event duplicates blocked)
        # - 20 comment.deleted events
        # - 140 non-matching comments (e.g. "Nice post!")
        print("\n2. Generating 500 synthetic webhook events with edge cases...")
        
        events = []
        user_ids = [f"usr_{i:03d}" for i in range(1, 51)] # 50 unique users
        
        # Genuine first comments for 50 users
        for i, uid in enumerate(user_ids):
            events.append({
                "event_id": f"evt_genuine_{i:03d}",
                "event_type": "comment.created",
                "data": {
                    "comment_id": f"cmt_gen_{i:03d}",
                    "post_id": "post_100",
                    "text": f"PRICE please! user {uid}",
                    "from": {"user_id": uid, "username": f"user_{uid}"}
                }
            })

        # 250 duplicate user comments for the same rule
        for i in range(250):
            uid = random.choice(user_ids)
            events.append({
                "event_id": f"evt_user_dup_{i:03d}",
                "event_type": "comment.created",
                "data": {
                    "comment_id": f"cmt_udup_{i:03d}",
                    "post_id": "post_100",
                    "text": "PRICE info again!",
                    "from": {"user_id": uid, "username": f"user_{uid}"}
                }
            })

        # 40 duplicate event_id redeliveries (exact same event_id)
        for i in range(40):
            target = events[i % 50]
            events.append({
                "event_id": target["event_id"],  # Same event_id
                "event_type": target["event_type"],
                "data": target["data"]
            })

        # 140 non-matching comments
        for i in range(140):
            uid = random.choice(user_ids)
            events.append({
                "event_id": f"evt_no_match_{i:03d}",
                "event_type": "comment.created",
                "data": {
                    "comment_id": f"cmt_nomatch_{i:03d}",
                    "post_id": "post_100",
                    "text": "Beautiful picture! ❤️",
                    "from": {"user_id": uid, "username": f"user_{uid}"}
                }
            })

        # Shuffle all 480 events
        random.shuffle(events)
        
        print(f"Total synthetic events generated: {len(events)}")
        print("Expected Expected Genuine Dispatches: 50")
        print("Expected Duplicate Blocks (user-rule + event_id): 290")

        # 3. Fire all events concurrently over 10 seconds
        print("\n3. Firing 480 webhook events concurrently over 10 seconds...")
        start_time = time.time()
        
        async def send_event(evt):
            body = json.dumps(evt).encode("utf-8")
            sig = generate_signature(body, settings.API_KEY)
            resp = await client.post(
                f"{base_url}/webhook",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-PseudoGram-Signature": sig
                }
            )
            return resp.status_code

        tasks = [send_event(evt) for evt in events]
        results = await asyncio.gather(*tasks)
        elapsed = time.time() - start_time
        print(f"Dispatched {len(results)} webhooks in {elapsed:.2f} seconds.")
        print(f"Status codes count: 200 OK -> {results.count(200)}, Others -> {len(results) - results.count(200)}")

        # 4. Monitor /stats progression until queued drops to 0
        print("\n4. Monitoring /stats progression during background processing...")
        for t in range(1, 30):
            await asyncio.sleep(2)
            stats_resp = await client.get(f"{base_url}/stats")
            stats = stats_resp.json()
            print(f"T+{(t*2)}s: {stats}")
            if stats["queued"] == 0 and (stats["sent"] > 0 or stats["failed"] > 0):
                print("\nAll pending tasks processed!")
                break

        # 5. Final Report & Ground Truth Audit
        final_stats = (await client.get(f"{base_url}/stats")).json()
        print("\n" + "=" * 60)
        print("FINAL E2E AUDIT RESULTS:")
        print(json.dumps(final_stats, indent=2))
        print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_e2e_stress_test())
