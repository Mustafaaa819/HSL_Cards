# Fix: "Could not reach the server" on localhost:4173

## Ground rules before touching anything
- `http://localhost:8000/` alone returning `{"detail":"Not Found"}` is **not
  a bug** — that route was never defined, it only ever answers specific
  paths (`/health`, `/rooms`, `/ws/{room_code}`). Don't "fix" that. If
  that's genuinely all that's being reported as broken, say so plainly and
  stop — the real app is at `4173`, not `8000`.
- The actual symptom to chase is: opening `http://localhost:4173` and
  seeing the red "Could not reach the server" toast on the lobby screen.
  That string comes from `frontend/src/api.js` (`ApiError('Could not reach
  the server', 0, ...)`) — it means the `fetch()` in there threw (network
  error, connection refused, or CORS rejection), not that the server
  returned an HTTP error status. Those are different failure modes with
  different fixes — find out which one it actually is, don't guess.

## Do this in order

1. **Kill anything stale first.** Check for leftover processes already
   bound to 8000 or 4173 from a previous session that didn't shut down
   cleanly (this has happened before — see `CLAUDE.md`'s note on stale dev
   servers causing "old code silently serving" confusion). Free both ports
   before starting anything new.

2. **Start the backend and CONFIRM it's actually listening, not just that
   the command returned:**
   ```
   cd backend
   .venv\Scripts\activate
   uvicorn app.main:app --reload --port 8000
   ```
   Read the actual terminal output for `Uvicorn running on
   http://127.0.0.1:8000`. Then independently verify from a second shell:
   `curl http://localhost:8000/health` should return `{"status":"ok"}`.
   If that curl fails, the problem is entirely on the backend side and the
   frontend is irrelevant right now — diagnose the backend's own startup
   output for the real error before going anywhere near the browser.

3. **Only once step 2's curl succeeds**, start the frontend:
   ```
   cd frontend
   npm run dev
   ```
   Confirm the terminal shows `Local: http://localhost:4173/` with no
   errors.

4. **Drive the actual browser yourself and look at what's really
   happening** — don't ask the human to keep reporting back what they see,
   use your own browser automation (Chrome extension / Playwright,
   whichever this environment has) to:
   - Navigate to `http://localhost:4173`.
   - Capture the console errors (not just the visible toast text).
   - Capture the Network tab entry for the failing request: what URL did
     it actually try to hit, what was the response status or was it a
     hard connection failure, and — if it got a response at all — does it
     carry `Access-Control-Allow-Origin` for `http://localhost:4173`
     (the CORS allowlist in `backend/app/main.py` was already edited to
     include 4173 — confirm that edit actually took effect and the
     backend process currently running is the one with that change, not a
     stale process started before the edit).

5. **Check for a Windows Firewall prompt.** The first time a new process
   (a freshly rebuilt `python.exe`/`node.exe`, or a new venv) starts
   listening on a port, Windows sometimes throws a "Windows Defender
   Firewall has blocked some features of this app" dialog that silently
   blocks incoming connections until a human clicks "Allow access" — and
   this dialog is a native OS popup that background/automated tooling
   cannot see or dismiss. This produces exactly a "connection refused /
   could not reach server" symptom from the browser while the terminal
   shows the server as running happily. You (Claude Code) can't check for
   this yourself — explicitly ask the human running this to check if
   that dialog appeared and got dismissed, or is sitting ignored behind
   another window.

6. **Report back specifically, not generically:**
   - Did `curl http://localhost:8000/health` succeed?
   - What did the browser's Network tab actually show for the failed
     request — connection refused, CORS rejection, or something else?
   - Is there any chance a stale server from an earlier session was still
     holding one of the ports?
   - Did you ask the human to check for a Windows Firewall prompt?

Don't declare this fixed on "restarted the servers, should be fine now" —
that's the same unverified hope that led to this loop. Confirm the actual
mechanism of failure before calling it done.
