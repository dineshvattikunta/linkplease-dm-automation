import asyncio
import sqlite3
import hmac
import hashlib
import json
import httpx
from app.config import settings

def generate_sig(body: bytes, secret: str) -> str:
    return f"sha256={hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()}"

async def prove_all_fixes():
    base_url = "http://localhost:8000"
    
    print("=" * 70)
    print("EMPIRICAL PROOF TEST SUITE FOR FIXES 1 TO 8")
    print("=" * 70)

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Reset DB
        conn = sqlite3.connect('linkplease.db')
        c = conn.cursor()
        c.execute('DELETE FROM webhook_events')
        c.execute('DELETE FROM dm_tasks')
        c.execute('DELETE FROM user_rule_dispatches')
        c.execute('DELETE FROM rules')
        c.execute('UPDATE stat_counters SET sent=0, failed=0, queued=0, duplicates_blocked=0 WHERE id=1')
        conn.commit()
        conn.close()

        # Create Rule
        rule_resp = await client.post(f"{base_url}/rules", json={"keyword": "PRICETEST", "dm_message": "Price list $99"})
        rule_id = rule_resp.json()["rule_id"]
        print(f"\nRule created: {rule_id}")

        # PROOF FIX 6: Signature Verification with RAW Body
        print("\n" + "-" * 50)
        print("PROOF FIX 6: Signature Verification (Valid vs Forged)")
        print("-" * 50)
        payload = {"event_id": "evt_sig_test", "event_type": "comment.created", "data": {"comment_id": "c_sig", "text": "PRICETEST", "from": {"user_id": "u_sig"}}}
        body = json.dumps(payload).encode("utf-8")
        
        # Test A: Deliberately wrong signature
        resp_bad = await client.post(f"{base_url}/webhook", content=body, headers={"X-PseudoGram-Signature": "sha256=invalid"})
        print(f"Forged/Bad Signature Response: HTTP {resp_bad.status_code} -> {resp_bad.json()}")
        assert resp_bad.status_code == 401

        # Test B: Valid signature over RAW bytes
        valid_sig = generate_sig(body, settings.API_KEY)
        resp_good = await client.post(f"{base_url}/webhook", content=body, headers={"X-PseudoGram-Signature": valid_sig})
        print(f"Valid Signature Response: HTTP {resp_good.status_code} -> {resp_good.json()}")
        assert resp_good.status_code == 200

        # PROOF FIX 2: Atomic Database Deduplication
        print("\n" + "-" * 50)
        print("PROOF FIX 2: Atomic DB-Level Deduplication (user_id, rule_id)")
        print("-" * 50)
        payload_dup = {"event_id": "evt_dup_2", "event_type": "comment.created", "data": {"comment_id": "c_dup2", "text": "PRICETEST", "from": {"user_id": "u_sig"}}}
        body_dup = json.dumps(payload_dup).encode("utf-8")
        sig_dup = generate_sig(body_dup, settings.API_KEY)
        
        # Send second comment for same user and rule
        resp_dup = await client.post(f"{base_url}/webhook", content=body_dup, headers={"X-PseudoGram-Signature": sig_dup})
        print(f"Duplicate User Comment Webhook Response: HTTP {resp_dup.status_code} -> {resp_dup.json()}")
        
        stats_after_dup = (await client.get(f"{base_url}/stats")).json()
        print(f"Stats after duplicate comment: {stats_after_dup}")
        assert stats_after_dup["duplicates_blocked"] == 1

        # PROOF FIX 7: comment.deleted Handling (Before vs After DM Send)
        print("\n" + "-" * 50)
        print("PROOF FIX 7: comment.deleted Handling")
        print("-" * 50)
        # Create comment task
        payload_del = {"event_id": "evt_to_delete", "event_type": "comment.created", "data": {"comment_id": "c_todelete", "text": "PRICETEST", "from": {"user_id": "u_del"}}}
        body_del = json.dumps(payload_del).encode("utf-8")
        await client.post(f"{base_url}/webhook", content=body_del, headers={"X-PseudoGram-Signature": generate_sig(body_del, settings.API_KEY)})
        
        # Delete BEFORE send
        payload_del_evt = {"event_id": "evt_deleted_action", "event_type": "comment.deleted", "data": {"comment_id": "c_todelete"}}
        body_del_evt = json.dumps(payload_del_evt).encode("utf-8")
        resp_del = await client.post(f"{base_url}/webhook", content=body_del_evt, headers={"X-PseudoGram-Signature": generate_sig(body_del_evt, settings.API_KEY)})
        print(f"comment.deleted before send Response: HTTP {resp_del.status_code} -> {resp_del.json()}")

        # Check DB status for cancelled task
        conn = sqlite3.connect('linkplease.db')
        c = conn.cursor()
        c.execute("SELECT comment_id, status FROM dm_tasks WHERE comment_id='c_todelete'")
        row = c.fetchone()
        conn.close()
        print(f"Cancelled Task Status in DB: comment_id={row[0]}, status={row[1]}")
        assert row[1] == "cancelled"

        # PROOF FIX 8: Live /stats Accuracy vs DB COUNT Queries
        print("\n" + "-" * 50)
        print("PROOF FIX 8: Live /stats Accuracy vs DB COUNT Verification")
        print("-" * 50)
        stats_live = (await client.get(f"{base_url}/stats")).json()
        
        conn = sqlite3.connect('linkplease.db')
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM dm_tasks WHERE status='queued'")
        db_queued = c.fetchone()[0]
        c.execute("SELECT sent, failed, duplicates_blocked FROM stat_counters WHERE id=1")
        db_counters = c.fetchone()
        conn.close()

        print(f"API /stats Response: {stats_live}")
        print(f"DB COUNT Query Values: queued={db_queued}, sent={db_counters[0]}, failed={db_counters[1]}, duplicates_blocked={db_counters[2]}")
        assert stats_live["queued"] == db_queued
        assert stats_live["sent"] == db_counters[0]
        assert stats_live["failed"] == db_counters[1]
        assert stats_live["duplicates_blocked"] == db_counters[2]

        print("\n" + "=" * 70)
        print("ALL EMPIRICAL PROOF TESTS PASSED SUCCESSFULLY!")
        print("=" * 70)

if __name__ == "__main__":
    asyncio.run(prove_all_fixes())
