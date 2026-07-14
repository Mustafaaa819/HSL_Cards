from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routers import health, ws_test

load_dotenv()

app = FastAPI(title="HSL Cards")

# Dev-only: allows the Vite dev server (localhost:5173) to reach the API/WS
# during local development. Not needed in production since the built
# frontend is served from this same origin (see static mount below).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(ws_test.router)

# In production (HF Spaces / Docker) the frontend is built and copied into
# this directory so a single container/port can serve both. In local dev
# this directory won't exist and the frontend runs via `npm run dev` instead.
_frontend_dist = Path(__file__).resolve().parent.parent / "static"
if _frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
