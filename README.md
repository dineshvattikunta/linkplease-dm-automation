# LinkPlease Instagram DM Automation Engine

A high-performance, resilient microservice built with **Python**, **FastAPI**, and **PostgreSQL** (with **SQLite WAL** fallback) designed to automate Instagram DMs under hostile API conditions—handling rate limits, transient 500 errors, out-of-order events, duplicate webhooks, HMAC signature security, and asynchronous DM delivery reconciliation.

---

## 🌐 Live Production Deployment

- 📊 **Live Stats**: https://linkplease-dm-automation-ol6m.onrender.com/stats
- 🛠️ **Interactive Swagger API Docs**: https://linkplease-dm-automation-ol6m.onrender.com/docs
- ❤️ **Health Check**: https://linkplease-dm-automation-ol6m.onrender.com/health
- 📖 **ReDoc Documentation**: https://linkplease-dm-automation-ol6m.onrender.com/redoc
- 🐙 **GitHub Repository**: https://github.com/dineshvattikunta/linkplease-dm-automation

---

## ✨ System Features & Capabilities

- **Core DM Automation**: Dynamic rule creation (`POST /rules`) supporting case-insensitive keyword matching and custom DM messaging.
- **HMAC SHA-256 Security**: Webhook signature verification (`X-PseudoGram-Signature`) computed directly over raw request bytes before JSON parsing. Rejects unauthorized or forged webhooks with `401 Unauthorized`.
- **Atomic Database Deduplication**: Enforces a DB-level UNIQUE constraint on `(user_id, rule_id)` to ensure duplicate user comments are blocked atomically with zero race conditions.
- **Sliding-Window Rate Limiter**: Enforces a strict cap of 9 requests per rolling 60-second window to prevent 429 rate limit breaches against the remote API.
- **Exponential Backoff Worker**: Background task processor that automatically retries transient `500 Internal Error` responses with exponential backoff (`2^attempts` seconds) up to a max retry limit.
- **Confirmed Delivery Reconciliation**: Polling worker (`GET /v1/dm/{dm_id}`) that updates DM state to `sent` **only** after remote delivery is confirmed as `DELIVERED`.
- **Intelligent Comment Deletion**: Listens for `comment.deleted` events and automatically cancels queued DM tasks before dispatch.
- **Dual Database Architecture**: Connects to Render Free **PostgreSQL** (`asyncpg`) in production for permanent persistence across restarts, and uses **SQLite (WAL mode)** for local development.

---

## 📋 API Contract Reference

### `POST /rules`
Creates a keyword automation rule.
- **Request Body**: `{"keyword": "PRICE", "dm_message": "Here is the price list: $99!"}`
- **Response (201 Created)**: `{"rule_id": "rule_12345", "keyword": "PRICE", "dm_message": "Here is the price list: $99!"}`

### `POST /webhook`
Receives Instagram comment events and enqueues DM dispatches.
- **Headers**: `X-PseudoGram-Signature: sha256=<hex_digest>`
- **Response (200 OK)**: `{"status": "ok"}`

### `GET /stats`
Retrieves live real-time system metrics.
- **Response (200 OK)**: `{"sent": 70, "failed": 5, "queued": 0, "duplicates_blocked": 1023}`

### `GET /health`
Returns service health status and configuration check.
- **Response (200 OK)**: `{"status": "healthy", "service": "LinkPlease Instagram DM Automation", "api_key_configured": true}`

### `POST /reset`
Resets stats and clears DM records for clean benchmarking.
- **Response (200 OK)**: `{"status": "ok", "message": "Database and stats reset clean"}`

---

## 🛠️ Local Development Quickstart

### 1. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 2. Run Automated Test Suite
```powershell
python -m pytest
```

### 3. Start Local Development Server
```powershell
python -m uvicorn app.main:app --reload --port 8000
```
Swagger UI will be accessible at `http://localhost:8000/docs`.

### 4. Run Production Simulation Stress Test
```powershell
python scripts/run_simulation.py https://linkplease-dm-automation-ol6m.onrender.com/webhook
```

---

## ⚙️ Environment Variables Reference

| Variable | Description | Default |
|---|---|---|
| `API_KEY` | Pseudogram API Secret Key | *(Set in .env)* |
| `PSEUDOGRAM_BASE_URL` | Pseudogram API Endpoint | `https://pseudogram-api.onrender.com` |
| `DATABASE_URL` | PostgreSQL or SQLite Connection URL | `sqlite+aiosqlite:///./linkplease.db` |
| `RATE_LIMIT_MAX_REQUESTS` | Max API calls per window | `9` |
| `RATE_LIMIT_WINDOW_SECONDS` | Rate limit window in seconds | `60` |
| `MAX_RETRY_ATTEMPTS` | Max retry attempts on 500 errors | `5` |
