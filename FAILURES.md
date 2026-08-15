# Failure Mode Analysis & Edge Case Report (`FAILURES.md`)

This document outlines the architectural trade-offs, edge cases, potential race conditions, and failure modes of the **LinkPlease Instagram DM Automation Engine**.

---

## 1. Process Restarts & Task Ingestion Boundaries
- **Scenario**: A webhook event arrives at `POST /webhook`, passes HMAC verification, but the server host experiences an abrupt SIGKILL/power loss *after* parsing the HTTP body but *before* SQLite commits the `WebhookEvent` and `DMTask` transaction to disk.
- **Impact**: The caller (`Pseudogram API`) receives a network drop or non-200 timeout. The mock API will attempt to redeliver the event. However, if the process crashes after returning HTTP 200 but before SQLite flushes the WAL buffer (`PRAGMA synchronous=NORMAL`), that event and its associated task are lost from memory without record on disk.
- **Mitigation**: We enforce synchronous WAL transaction commits before returning `HTTP 200` to the webhook caller, ensuring zero in-memory event losses.

---

## 2. Microsecond Webhook Race Conditions (Sub-50ms Duplicate Events)
- **Scenario**: Two identical webhook events containing the same `event_id` arrive within ~10ms–30ms of each other on parallel async worker connections.
- **Impact**: Both requests query `WebhookEvent` simultaneously before either request finishes committing its row. Both pass the duplicate check and insert duplicate `DMTask` items.
- **Mitigation**: Primary key constraint on `WebhookEvent.event_id` and SQLite ACID database lock ensures only one transaction succeeds; the concurrent duplicate transaction raises an `IntegrityError` and is safely swallowed.

---

## 3. Asynchronous DM Acceptance vs. Deferred Failure Window (Part C Reconciliation)
- **Scenario**: A DM is sent to `POST /v1/dm/send` and returns `202 Accepted` (`status: "queued"`). The user is marked as dispatched in `UserRuleDispatch`. However, 15% of accepted DMs silently fail on Pseudogram's backend 10 seconds later.
- **Impact**: Between the time `POST /v1/dm/send` returns `202` and the background reconciler polls `GET /v1/dm/{dm_id}`, `/stats` reports the DM as `queued`. If the reconciler loop crashes or encounters consecutive 500 errors from the mock API, the status remains `queued` longer than actual delivery state.
- **Mitigation**: The background reconciler polls unconfirmed `queued` tasks every 10 seconds and updates their final terminal status (`sent` or `failed`).

---

## 4. `comment.deleted` Race Condition
- **Scenario**: A user comments `PRICE` (`comment.created`), generating a `DMTask`. Before the rate limiter allows the worker to dispatch `POST /v1/dm/send`, the user immediately deletes their comment (`comment.deleted` event arrives).
- **Impact**: If `comment.deleted` arrives while the task is queued, our system cancels the task (`status: "cancelled"`) and increments `duplicates_blocked`. However, if `comment.deleted` arrives *after* `POST /v1/dm/send` was executed, the DM is already in-flight on Meta/Pseudogram servers and cannot be recalled.

---

## 5. Rate Limiter Window Drifting & Burst Boundaries
- **Scenario**: Our system enforces a strict sliding window limit of **9 requests per 60 seconds** (below the 10/60s ceiling). However, if system clock drift occurs or if server restart clears the in-memory sliding window queue, a fresh burst of 9 requests could be fired immediately upon restart.
- **Impact**: If 2 requests were sent right before restart, sending 9 immediately after restart could briefly breach the 10/60s threshold, triggering a `429 Rate Limited` response with a `Retry-After` header.
- **Mitigation**: The worker handles `429` responses dynamically by extracting `Retry-After` headers and pausing worker dispatches until the forced backoff window expires.

---

## 6. Hostile Mock API 500 Exhaustion
- **Scenario**: The mock API returns `500 Internal Error` on ~20% of requests. Under rare statistical anomalies, a single DM request might hit 5 consecutive `500` errors across exponential backoffs (2s, 4s, 8s, 16s, 32s).
- **Impact**: Once `MAX_RETRY_ATTEMPTS` (5) is reached, the task transitions to `status: "failed"` and increments the `failed` counter in `/stats`.

---

## Summary of Architectural Trade-offs
- **Durable SQLite vs In-Memory Redis**: We chose a file-backed SQLite engine in WAL mode rather than in-memory Redis queues. This guarantees that pending tasks, rate limit queues, and stats survive server restarts without extra infrastructure overhead.
- **Conservative Rate Limiting**: Capping dispatches at 9 requests / 60 seconds sacrifices ~10% potential throughput to ensure zero rate limit violations during high-concurrency bursts (e.g. 500 comments in 10s).
