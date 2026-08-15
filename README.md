# LinkPlease Instagram DM Automation Engine

A high-performance, resilient microservice built with **Python**, **FastAPI**, and **SQLite (WAL mode)** designed to automate Instagram DMs while gracefully handling hostile API conditions (rate limits, transient 500s, out-of-order events, duplicate webhooks, and asynchronous DM delivery failures).

---

## Features & Scope Coverage

- **Part A (Required)**: 
  - Dynamic rule creation (`POST /rules`) with case-insensitive keyword matching.
  - User-rule deduplication: the same user never receives duplicate DMs for the same rule.
  - Zero lost DMs during transient API errors (`500 Internal Error` handled with exponential backoff).
- **Part B**:
  - Webhook signature verification (`X-PseudoGram-Signature: sha256=<hex>` HMAC SHA-256).
  - High-precision live `/stats` endpoint (`sent`, `failed`, `queued`, `duplicates_blocked`).
- **Part C**:
  - Asynchronous status reconciliation worker (`GET /v1/dm/{dm_id}`).
  - Intelligent `comment.deleted` event handling.
  - Strict token/sliding-window rate limiter ensuring maximum 9 requests per rolling 60 seconds.

---

## Configuration & Environment Variables

All settings are dynamically configured in `.env` (or environment variables on host platforms). No values are hardcoded:

```ini
# Mock API Credentials
API_KEY=your_api_key_here
PSEUDOGRAM_BASE_URL=https://pseudogram-api.onrender.com

# User Profile Details
USER_NAME=Vattikunta Dinesh Chowdary
USER_EMAIL=vattikuntad@gmail.com
USER_PHONE=+91 7989853264
USER_LINKEDIN=https://www.linkedin.com/in/dinesh-vattikunta
GITHUB_REPO_URL=https://github.com/vattikuntadinesh/linkplease-dm-automation
WORKING_URL=https://linkplease-dm-automation.onrender.com
LOOM_URL=https://loom.com/share/placeholder

# Server & Database Settings
PORT=8000
HOST=0.0.0.0
DATABASE_URL=sqlite+aiosqlite:///./linkplease.db

# Rate Limiter & Concurrency Controls (Mock API max limit is 10/60s)
RATE_LIMIT_MAX_REQUESTS=9
RATE_LIMIT_WINDOW_SECONDS=60
```

---

## Local Quickstart

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the FastAPI Application
```bash
uvicorn app.main:app --reload --port 8000
```
API Documentation will be available at `http://localhost:8000/docs`.

### 3. Run Automated Unit & Integration Tests
```bash
python -m pytest
```

---

## Simulation Benchmark Testing

To trigger a 500-event stress test against the mock API and verify your stats against server truth:

```bash
python scripts/run_simulation.py https://your-app-url.onrender.com/webhook
```

---

## Deployment (1-Click Blueprint for Render / Railway)

1. Push this repository to GitHub.
2. Log in to [Render.com](https://render.com) or [Railway.app](https://railway.app).
3. Select **New Web Service** and connect your repository.
4. Render automatically reads `render.yaml` or `Procfile`.
5. Set environment variable `API_KEY` to your key:
   `YOUR_API_KEY_HERE`

---

## Script for 3-Minute Loom Video

For your 3-minute Loom video, answer these 2 required questions:

1. **Tradeoff Made & What Was Given Up**:
   > *"We traded raw in-memory speed for 100% durable disk persistence using SQLite in WAL mode. By committing tasks to disk before returning HTTP 200 on webhooks and setting a conservative 9 req/60s rate limit, we gave up peak instantaneous throughput (~10% slower burst drain) to guarantee zero data loss on server restarts and zero 429 rate limit breaches."*
2. **What You'd Do Differently With One More Week**:
   > *"With one more week, I would deploy a multi-node worker architecture using Redis Stream / RabbitMQ with distributed locks, enabling multi-tenant rate limiting across multiple creator accounts simultaneously, and add web sockets for real-time live metrics dashboards."*

---

## Final Submission

To submit the assignment once deployed:

```bash
python scripts/submit_assignment.py
```
