# StarHoop.ai — Startup Guide

**Complete step-by-step instructions to start the entire system from a cold boot.**

This guide assumes your PC has just been turned on and you want to resume development on the StarHoop.ai project.

---

## Prerequisites

Before following this guide, ensure you have installed:
- **Docker Desktop** (for Docker Compose)
- **Python 3.12+** (in PATH)
- **ngrok** (download from [ngrok.com](https://ngrok.com) or `choco install ngrok`)
- **Modal CLI** (for Modal deployment) — optional if you've already deployed

---

## Startup Sequence

Follow these steps **in order**, opening **separate PowerShell terminals** for each.

---

## Terminal 1️⃣ — Start Docker Containers (PostgreSQL + API)

**Purpose:** Start PostgreSQL database and API container.

```powershell
# Navigate to project directory
Set-Location 'C:\Users\einav\OneDrive\Desktop\HoopStar.ai\StarHoop.ai'

# Start all Docker services (PostgreSQL, API in background)
docker compose up -d

# Verify containers are running
docker compose ps
```

**Expected output:**
```
NAME      IMAGE             STATUS
starhoop-db-1    postgres:16   Up (healthy)
starhoop-api-1   starhoop:api  Up
```

**Troubleshooting:**
- If containers won't start: `docker compose logs` (shows errors)
- To rebuild containers: `docker compose up -d --build`
- To reset database: `docker compose down -v` (⚠️ deletes data)

---

## Terminal 2️⃣ — Start ngrok Tunnel (Webhook Bridge)

**Purpose:** Create a public tunnel so Modal can POST results back to your local API.

```powershell
# Navigate to project directory
Set-Location 'C:\Users\einav\OneDrive\Desktop\HoopStar.ai\StarHoop.ai'

# Start ngrok tunnel on port 8000 (FastAPI runs here)
ngrok http 8000
```

**Expected output:**
```
ngrok by @inconshreveable

Session Status      online
Account             [your-account]
Version             3.x.x
Region              us
Latency             xx ms
Web Interface       http://127.0.0.1:4040

Forwarding          https://xxxx-xx-xxx-xx-xx.ngrok-free → http://localhost:8000
```

**⚠️ IMPORTANT — Copy the HTTPS URL**

Copy the `Forwarding` HTTPS URL (e.g., `https://thrift-fraying-plentiful.ngrok-free`).

**Keep this terminal open.** ← ngrok must run continuously for webhooks to work.

---

## Terminal 3️⃣ — Update .env with ngrok URL

**Purpose:** Point the API to your new ngrok tunnel so Modal can reach it.

```powershell
# Navigate to project directory
Set-Location 'C:\Users\einav\OneDrive\Desktop\HoopStar.ai\StarHoop.ai'

# Open .env in your editor
notepad .env
```

**Find this line:**
```
WEBHOOK_BASE_URL=https://old-url-here.ngrok-free
```

**Replace with your new ngrok URL (from Terminal 2️⃣):**
```
WEBHOOK_BASE_URL=https://xxxx-xx-xxx-xx-xx.ngrok-free
```

**Save and close.**

---

## Terminal 4️⃣ — Start FastAPI Server

**Purpose:** Launch the HTTP API server with auto-reload enabled.

```powershell
# Navigate to project directory
Set-Location 'C:\Users\einav\OneDrive\Desktop\HoopStar.ai\StarHoop.ai'

# Set Python path and start API
$env:PYTHONPATH='src'
python -m uvicorn app.main:app --reload --port 8000
```

**Expected output:**
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete
```

**Keep this terminal open.** ← FastAPI must run continuously.

---

## ✅ System Ready — Verify Everything Works

Once all 4 terminals are running, test the system:

### Test 1: Health Check
```powershell
# In a NEW terminal (Terminal 5️⃣)
curl http://localhost:8000/health
```

**Expected response:**
```json
{"status":"ok","database":"connected"}
```

### Test 2: View API Docs
Open in your browser:
```
http://localhost:8000/docs
```

You should see the **Swagger UI** with all endpoints listed.

### Test 3: Check ngrok Dashboard
Open in your browser:
```
http://localhost:4040
```

You should see real-time logs of webhook requests.

---

## Full System Architecture (What's Running)

```
┌─────────────────────────────────────────────────────────────────┐
│ TERMINALS ACTIVE                                                │
├─────────────────────────────────────────────────────────────────┤
│ Terminal 1️⃣  (Background, Docker)                                │
│   └─ PostgreSQL at localhost:5432                              │
│   └─ API container (internal)                                  │
│                                                                  │
│ Terminal 2️⃣  (Foreground, ngrok)                                 │
│   └─ ngrok tunnel: https://xxx.ngrok-free → localhost:8000     │
│   └─ WebSocket monitoring at http://localhost:4040             │
│                                                                  │
│ Terminal 3️⃣  (File edit, then close)                             │
│   └─ .env updated with ngrok URL                               │
│                                                                  │
│ Terminal 4️⃣  (Foreground, FastAPI)                               │
│   └─ FastAPI on http://localhost:8000                          │
│   └─ Auto-reload enabled (edit src/ files, API restarts)       │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│ DATA FLOW                                                         │
├─────────────────────────────────────────────────────────────────┤
│ 1. Coach uploads video → FastAPI (local 8000)                   │
│ 2. FastAPI stores video in R2 (Cloudflare)                      │
│ 3. FastAPI triggers Modal job (async)                           │
│ 4. Modal runs CV pipeline on GPU                                │
│ 5. Modal POSTs results → ngrok tunnel → localhost:8000 → DB    │
│ 6. Coach polls status → FastAPI → PostgreSQL                    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Common Commands (While Running)

### Upload a Test Video
```powershell
curl -X POST `
  -H "Content-Type: multipart/form-data" `
  -F "file=@C:\path\to\game.mp4" `
  -F "team_id=1" `
  http://localhost:8000/api/videos/upload
```

### Poll Job Status
```powershell
# Replace {job_id} with ID from upload response
curl http://localhost:8000/api/videos/16
```

### Generate Annotated Video
```powershell
curl -X POST http://localhost:8000/api/videos/16/exports/annotated
```

### Run Action Detection
```powershell
curl -X POST http://localhost:8000/api/videos/16/actions/auto
```

### View API Logs (Terminal 4️⃣)
Watch Terminal 4️⃣ for real-time logs of every request.

### View Docker Logs
```powershell
docker compose logs -f api   # API container logs
docker compose logs -f db    # PostgreSQL logs
```

### View ngrok Logs (Terminal 2️⃣)
Watch Terminal 2️⃣ for webhook POST activity (shows when Modal calls back).

---

## Shutdown (End of Day)

### Graceful Shutdown
1. **Terminal 4️⃣** (FastAPI) — Press `Ctrl+C`
2. **Terminal 2️⃣** (ngrok) — Press `Ctrl+C`
3. **Terminal 1️⃣** (Docker) — Run:
   ```powershell
   docker compose down
   ```

### Full Reset (Delete Database)
```powershell
docker compose down -v   # ⚠️ Deletes PostgreSQL data
docker compose up -d     # Start fresh
```

---

## Troubleshooting

### Issue: "Docker daemon is not running"
**Solution:**
- Open Docker Desktop app (search "Docker" in Start menu)
- Wait for it to fully boot (~1 minute)
- Try `docker compose up -d` again

### Issue: "Port 5432 is already in use"
**Solution:**
```powershell
docker ps                          # List running containers
docker stop starhoop-db-1          # Stop conflicting container
docker compose up -d               # Try again
```

### Issue: "ngrok says 'Invalid auth token'"
**Solution:**
1. Go to [ngrok.com](https://ngrok.com) and sign up (free)
2. Copy your auth token from the dashboard
3. Run: `ngrok config add-authtoken YOUR_TOKEN_HERE`

### Issue: "FastAPI won't start — module not found"
**Solution:**
```powershell
# Make sure PYTHONPATH is set
$env:PYTHONPATH='src'

# Then try again
python -m uvicorn app.main:app --reload --port 8000
```

### Issue: "Modal webhook POST not reaching API"
**Check:**
1. ngrok is running (Terminal 2️⃣)
2. `.env` has correct `WEBHOOK_BASE_URL`
3. FastAPI is running (Terminal 4️⃣)
4. Check `http://localhost:4040` to see if POST requests arrive at all

---

## Next Steps (Development)

**After startup is confirmed working:**

1. **Milestone 5 (Clip Extraction)** — Start implementing highlight clip extraction
2. **Test with Job 16** — Upload test video and verify E2E pipeline
3. **Modal Deployment** — Ensure `modal deploy modal_app/cv_app.py` has been run once
4. **Monitor Logs** — Watch Terminal 4️⃣ (FastAPI) and Terminal 2️⃣ (ngrok) during uploads

---

## Quick Reference Card

Print this for your desk:

```
STARTUP (in order):
1️⃣  Terminal 1 → docker compose up -d
2️⃣  Terminal 2 → ngrok http 8000 (copy HTTPS URL)
3️⃣  Terminal 3 → notepad .env (update WEBHOOK_BASE_URL)
4️⃣  Terminal 4 → $env:PYTHONPATH='src'; python -m uvicorn app.main:app --reload --port 8000

VERIFY:
curl http://localhost:8000/health
Browser: http://localhost:8000/docs

SHUTDOWN:
Ctrl+C in Terminal 4️⃣ and 2️⃣
docker compose down

LOGS:
Terminal 4️⃣ = FastAPI logs
Terminal 2️⃣ = ngrok webhook logs
docker compose logs -f api = Docker API logs
docker compose logs -f db = PostgreSQL logs
```

---

**Questions?** Check [README.md](README.md) for architecture details or error messages above.

**Last updated:** June 14, 2026
