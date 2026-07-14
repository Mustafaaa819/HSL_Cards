---
title: HSL Cards
emoji: 🃏
colorFrom: green
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# HSL Cards

Real-time multiplayer card game (2–5 players, mobile-first web app). **This is Phase 0: scaffolding only** — a FastAPI + WebSocket backend and a React + Vite frontend wired together end-to-end via a throwaway echo test. No game logic yet; see `docs/RULES.md` (you add it) for the rules that later phases will implement.

## Project structure

```
backend/
  app/
    main.py           # FastAPI app, CORS, static mount for prod
    routers/
      health.py        # GET /health
      ws_test.py        # WS /ws/test (echo) — real rooms go in a sibling router later
  requirements.txt
frontend/
  src/
    App.jsx            # WS echo test page
docs/
  RULES.md              # <- drop your finalized rules file here
Dockerfile               # single-container build for HF Spaces / Render
```

## Run the backend locally

```bash
cd backend
python -m venv .venv        # if you don't already have one
.venv/Scripts/activate       # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Check it's up: `curl http://localhost:8000/health` should return `{"status":"ok"}`.

## Run the frontend locally

```bash
cd frontend
npm install
npm run dev
```

Open the printed URL (defaults to `http://localhost:5173`). `frontend/.env.development.local` already points the dev client at `ws://localhost:8000/ws/test` — that's only needed in dev, since frontend and backend run as separate servers; in production they're served from the same origin and the WS URL is auto-derived. (Deliberately named `.env.development.local`, not `.env.local` — Vite loads `.env.local` into production builds too, which would have baked this dev-only override into the deployed image.)

## Verify the WebSocket echo works end-to-end

1. Start the backend (`uvicorn app.main:app --reload --port 8000`) and the frontend (`npm run dev`) in two terminals.
2. Open the frontend URL in a browser. The status line should switch from `connecting` to `connected` — that means the browser opened a real WebSocket to the FastAPI server, not a mock.
3. Type a message and hit Send. It should appear twice in the log: once labeled `sent` (optimistic local echo) and once labeled `echoed` (the reply that actually came back over the wire from `/ws/test` on the backend). If only the `sent` line shows up, the round trip is broken — check the backend terminal for errors and the browser devtools Network tab's WS frames.
4. To confirm it's mobile-first (not desktop squeezed down), open devtools' device toolbar and set the viewport to 390px wide — the layout should already fit without any horizontal scroll or awkward reflow, since it was built at that width from the start.

## Deployment

A single multi-stage `Dockerfile` at the repo root builds the frontend, copies the static output into the FastAPI app's `static/` directory, and serves both from one container/port — matching the Hugging Face Spaces Docker SDK convention (port 7860, configurable via `$PORT` so the same image also runs on Render).

### Is Hugging Face Spaces safe for this project's WebSockets?

**No, not confidently — treat it as unproven, not as the primary deploy target.** I checked current (2025–2026) reports rather than assuming: there's an active Hugging Face forum thread describing FastAPI WebSocket endpoints returning **HTTP 404 on Spaces**, i.e. the Spaces proxy rejecting the WS upgrade before it ever reaches the container — the exact stack this project uses. There are also multiple current reports of Docker Spaces hitting 503s and dropped connections unrelated to WS specifically, suggesting the proxy layer isn't rock-solid for arbitrary long-lived container traffic. Free-tier Spaces also sleep after 48h of inactivity (not a mid-game risk, but a cold-start risk for whoever connects first).

None of this is disqualifying — Gradio apps do use WebSockets successfully on Spaces — but Gradio's client has its own long-polling fallback specifically *because* raw WS wasn't reliably to depend on through that proxy. A plain FastAPI `WebSocket` endpoint doesn't get that fallback for free.

**Recommendation:** target **Render** or **Fly.io** (free tier) as the actual deploy for playtesting with the friend group — both have well-documented, unqualified WebSocket support through their standard proxies. Keep the HF Spaces `Dockerfile` here and try deploying it in parallel since it costs nothing extra, but validate the WS connection actually survives a real multiplayer session there before trusting it for game night. If it works, great, one less thing to maintain; if it doesn't, you already have Render/Fly.io as the real target and haven't lost anything.
