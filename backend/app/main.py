from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routers import game_ws, health, rooms, ws_test

load_dotenv()

app = FastAPI(title="HSL Cards")

# Dev-only: allows the Vite dev server to reach the API/WS during local
# development. Not needed in production since the built frontend is served
# from this same origin (see static mount below). 4173 is the pinned dev
# port (5173 falls in a Windows/Hyper-V excluded range on the dev machine —
# see frontend/vite.config.js); 5173 is kept for machines without that issue.
#
# A hardcoded port list here is fragile: if something else is already
# holding 4173, Vite silently picks the next free port (4174, 4175, ...)
# and every request from the browser gets rejected by CORS with a generic
# "network error" that's indistinguishable from the backend actually being
# down. `vite.config.js` now sets `strictPort: true` so Vite refuses to
# silently drift instead — but allow a small range here too as a second
# line of defense against exactly this class of confusion.
_DEV_PORTS = ["4173", "4174", "4175", "5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in _DEV_PORTS
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(rooms.router)
app.include_router(ws_test.router)  # before game_ws so literal /ws/test wins over /ws/{room_code}
app.include_router(game_ws.router)

# In production (HF Spaces / Docker) the frontend is built and copied into
# this directory so a single container/port can serve both. In local dev
# this directory won't exist and the frontend runs via `npm run dev` instead.
_frontend_dist = Path(__file__).resolve().parent.parent / "static"
if _frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="frontend")
