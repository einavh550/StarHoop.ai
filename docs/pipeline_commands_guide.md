# HoopStar.ai — Full Pipeline Command Guide

End-to-end process for uploading a video and getting a finished highlight reel.

---

## Prerequisites (run once when you start your PC)

```powershell
# 1. Start Docker containers
docker compose up -d

# 2. Start ngrok tunnel (keep this terminal open)
ngrok http 8000
```

---

## Stage 1 — Upload the video

```bash
curl.exe -X POST "http://localhost:8000/api/videos/upload" `
  -F "file=@C:/Users/einav/OneDrive/Desktop/yourvideo.mp4" `
  -F "team_id=13"
```

**Response gives you a `job_id` — note it down.**
Example response: `{"job_id": 23, "status": "pending", "message": "..."}`

---

## Stage 2 — Monitor processing (Modal GPU is running)

```bash
# Run every 30–60 seconds until status = "completed"
curl.exe "http://localhost:8000/api/videos/23"
```

Watch for these fields in the response:
- `"status": "processing"` → still running
- `"progress_percent": 64.5` → how far along
- `"status": "completed"` → ready to proceed to Stage 3

> Typical wait time: **15–30 minutes** for a full game video.

---

## Stage 3 — Run player mapping

```bash
curl.exe -X POST "http://localhost:8000/api/videos/23/player_mapping/auto?team_id=13"
```

The response lists every detected track with `suggested_player_name` and `match_rating`.
Check that your target player appears with `match_rating: "low"` or better.

---

## Stage 4 — Extract annotated highlight reel

Pick the player you want using their `player_id`:

| Jersey | Player | player_id |
|--------|--------|-----------|
| #22 | Raylon Moats | 39 |
| #10 | Colton Large | 40 |
| #23 | Preston Brookins | 36 |
| #24 | Blayze Hensley | 34 |
| #52 | Brayden Gunnels | 37 |
| #40 | Owen Nunemaker | 38 |
| #43 | Cayden Bradley | 35 |
| #1  | David Monesmith | 41 |
| #15 | Ian Pepin | 42 |

```bash
# Replace player_id with the value from the table above
# This takes 5–10 minutes — wait for it to finish
curl.exe -X POST "http://localhost:8000/api/videos/23/highlights/extract?player_id=39"
```

**Response gives you a `reel_id` — note it down.**
Example response: `{"reel_id": 15, "clip_count": 8, ...}`

---

## Stage 5 — Compose the reel (adds music, intro, watermark)

```bash
# Replace 23 with your job_id and 15 with your reel_id
curl.exe -X POST "http://localhost:8000/api/videos/23/highlights/15/compose"
```

**Response gives you a `composed_reel_id` — note it down.**
Example response: `{"composed_reel_id": 24, "total_duration_sec": 40.2, ...}`

---

## Stage 6 — Download to Desktop

```bash
# Replace 23 / 15 / 24 with your job_id / reel_id / composed_reel_id
curl.exe "http://localhost:8000/api/videos/23/highlights/15/compose/24/download" `
  -L --output "$env:USERPROFILE\OneDrive\Desktop\player_reel.mp4"
```

The finished `.mp4` will appear on your Desktop.

---

## Full Pipeline Summary

| Stage | Command | Wait time | What you get |
|-------|---------|-----------|--------------|
| 1 · Upload | `POST /api/videos/upload` | Instant | `job_id` |
| 2 · Monitor | `GET /api/videos/{job_id}` | 15–30 min | `status: completed` |
| 3 · Map players | `POST /api/videos/{job_id}/player_mapping/auto?team_id=13` | ~5 sec | Player names confirmed |
| 4 · Extract reel | `POST /api/videos/{job_id}/highlights/extract?player_id=X` | 5–10 min | `reel_id` |
| 5 · Compose reel | `POST /api/videos/{job_id}/highlights/{reel_id}/compose` | ~1 min | `composed_reel_id` |
| 6 · Download | `GET /api/videos/{job_id}/highlights/{reel_id}/compose/{composed_id}/download` | Instant | `.mp4` on Desktop |

---

## Already-processed reels (job 22 — bremenvstriton15.mp4)

These can be downloaded immediately without re-running the pipeline:

```bash
# Raylon Moats #22
curl.exe "http://localhost:8000/api/videos/22/highlights/12/compose/21/download" `
  -L --output "$env:USERPROFILE\OneDrive\Desktop\raylon_moats_reel.mp4"

# Colton Large #10
curl.exe "http://localhost:8000/api/videos/22/highlights/13/compose/22/download" `
  -L --output "$env:USERPROFILE\OneDrive\Desktop\colton_large_reel.mp4"

# Preston Brookins #23
curl.exe "http://localhost:8000/api/videos/22/highlights/14/compose/23/download" `
  -L --output "$env:USERPROFILE\OneDrive\Desktop\preston_brookins_reel.mp4"
```
