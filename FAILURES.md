# Failure Mode Analysis & Edge Case Report (`FAILURES.md`)

This document outlines the architectural trade-offs, edge cases, potential race conditions, and failure modes of the **LinkPlease Instagram DM Automation Engine** deployed on **Render Free PostgreSQL**.

---

## 1. Process Restarts & Task Ingestion Boundaries
- **Scenario**: A webhook event arrives at `POST /webhook`, passes HMAC verification, but the web service container experiences an abrupt restart or redeploy *after* parsing the HTTP body but *before* PostgreSQL commits the `WebhookEvent` and `DMTask` transaction to disk.
- **Impact**: The caller (`Pseudogram API`) receives a network drop or non-200 timeout and will attempt redelivery. If the process restarts *after* returning HTTP 200, PostgreSQL ACID guarantees ensure that the task is committed to disk and will not be lost.
- **Mitigation**: We enforce explicit database transaction commits before returning `HTTP 200` to the webhook caller. All pending tasks, user dispatches, and stat counters are persisted in an external PostgreSQL database (`linkplease-db`), guaranteeing zero in-memory data loss across web container redeploys or restarts.

---

## 2. Microsecond Webhook Race Conditions (Sub-50ms Duplicate Events)
- **Scenario**: Two identical webhook events containing the same `event_id` or two comments from the same user for the same rule arrive within ~10ms–30ms of each other on parallel async connections.
- **Impact**: Without database-level constraints, concurrent async tasks could query the DB simultaneously before either commits, causing duplicate DM dispatches.
- **Mitigation**: We enforce database-level `PRIMARY KEY` constraints on `WebhookEvent.event_id` and a `UNIQUE(user_id, rule_id)` constraint on `UserRuleDispatch`. When concurrent duplicates arrive, PostgreSQL raises an `IntegrityError`, which our application catches atomically to increment `duplicates_blocked` and discard the duplicate event cleanly.

---

## 3. Asynchronous DM Acceptance vs. Deferred Failure Window (Part C Reconciliation)
- **Scenario**: A DM request is sent to `POST /v1/dm/send` and returns `202 Accepted` (`status: "queued"`). The user reservation is committed in `UserRuleDispatch`. However, ~15% of accepted DMs silently fail on Pseudogram's backend 10 seconds later.
- **Impact**: Between the time `POST /v1/dm/send` returns `202` and the background reconciler polls `GET /v1/dm/{dm_id}`, `/stats` reports the DM as `queued`. If the reconciler loop encounters transient 500 errors from the mock API, the status remains `queued` until the next polling cycle.
- **Mitigation**: The background reconciler polls unconfirmed `queued` tasks every 10 seconds and updates their final terminal status (`sent` or `failed`) based on ground truth from `GET /v1/dm/{dm_id}`.

---

## 4. `comment.deleted` Race Condition
- **Scenario**: A user comments `PRICE` (`comment.created`), generating a `DMTask`. Before the rate limiter allows the worker to dispatch `POST /v1/dm/send`, the user deletes their comment (`comment.deleted` event arrives).
- **Impact**: If `comment.deleted` arrives while the task is queued in the database, our handler cancels the task (`status: "cancelled"`) and increments `duplicates_blocked`. However, if `comment.deleted` arrives *after* `POST /v1/dm/send` was executed, the DM is already in-flight on Meta/Pseudogram servers and cannot be recalled.

---

## 5. Rate Limiter Window Drifting & Burst Boundaries
- **Scenario**: Our system enforces a strict sliding window limit of **9 requests per 60 seconds** (below the 10/60s ceiling). If system clock drift occurs or if server restart clears the in-memory sliding window queue, a fresh burst of requests could be fired.
- **Impact**: If requests were sent right before restart, sending 9 immediately after restart could briefly breach the 10/60s threshold, triggering a `429 Rate Limited` response with a `Retry-After` header.
- **Mitigation**: The worker handles `429` responses dynamically by extracting `Retry-After` headers and pausing worker dispatches until the forced backoff window expires.

---

## 6. Hostile Mock API 500 Exhaustion
- **Scenario**: The mock API returns `500 Internal Error` on ~20% of requests. Under rare statistical anomalies, a single DM request might hit 5 consecutive `500` errors across exponential backoffs (2s, 4s, 8s, 16s, 32s).
- **Impact**: Once `MAX_RETRY_ATTEMPTS` (5) is reached, the task transitions to `status: "failed"` and increments the `failed` counter in `/stats`.

---

## Summary of Architectural Trade-offs
- **External PostgreSQL vs Ephemeral Storage**: We use a hosted PostgreSQL instance (`linkplease-db`) connected via `asyncpg`. This guarantees that pending tasks, rate limit queues, and stats survive web service container redeploys and restarts without relying on ephemeral container disks.
- **Conservative Rate Limiting**: Capping dispatches at 9 requests / 60 seconds sacrifices ~10% potential throughput to ensure zero rate limit violations during high-concurrency bursts (e.g. 500 comments in 10s).
