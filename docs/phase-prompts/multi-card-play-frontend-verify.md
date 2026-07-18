# Follow-up prompt: actually verify the multi-card play UI

## What happened last session, for context
The multi-card "Throw multiples" UI was implemented (`GameScreen.jsx`,
`Card.jsx`, `App.css`) but never actually verified in a browser. The dev
server kept failing with exit code 1, which turned out to be **two stacked,
unrelated problems**, both now fixed — the UI itself has still not been
visually confirmed to work:

1. `frontend/node_modules` had a corrupted Rolldown native binding (a known
   npm optional-dependency bug). Fixed: `node_modules` and
   `package-lock.json` were deleted and reinstalled clean.
2. Port 5173 (Vite's default) falls inside a Windows/Hyper-V excluded TCP
   port range on this machine (confirmed via `netsh interface ipv4 show
   excludedportrange protocol=tcp` — `5173-5272` is blocked, along with
   several other nearby ranges). Fixed: `frontend/vite.config.js` now pins
   `server.port` to `4173`, which sits clear of every excluded range.

Working around problem 2, the previous session built the frontend for
production and served it from the backend's existing static mount
(`backend/app/main.py`, the `StaticFiles` mount at `_frontend_dist`) on port
8000 instead of running the real Vite dev server. **That workaround is no
longer needed and shouldn't be used going forward** — now that port 4173 is
free, run the actual dev server. Testing against a stale production build
instead of live dev server output is not equivalent and shouldn't be how
this gets verified.

## What to do

1. **Clean up stray state first.** There's an untracked `package-lock.json`
   at the repo root (`F:\PythonProjects\HSL_Cards\package-lock.json`) with
   no corresponding root `package.json` — it doesn't belong there, almost
   certainly left over from an `npm install` run from the wrong directory
   during troubleshooting. Delete it. Don't touch `frontend/package-lock.json`
   (that one's legitimate, from the real reinstall).

2. **Start both dev servers for real, not the static-build workaround:**
   - Backend: whatever rigged/test server setup was used before (the
     `rigged_server.py` launcher with the deterministic hand from last
     session, or the real app if that's easier) on port 8000.
   - Frontend: `npm run dev` in `frontend/` — should now bind to `4173`
     per the updated `vite.config.js`. Confirm the terminal output actually
     shows it listening before moving on; don't assume success from a lack
     of an immediate error.
   - Start these so the tool call returns control (background/non-blocking).
     Last session hit an "API Error: Stream idle timeout" after starting a
     server — if that was caused by running the dev server in a blocking
     foreground call, use whatever this environment's actual backgrounding
     mechanism is instead of a plain blocking command.

3. **Update `multi_play_pass.py`** (wherever it currently lives — it was
   written into a scratchpad path last session, not the repo) so its
   `FRONTEND` constant points at `http://localhost:4173` instead of `5173`
   or the port-8000 static-build URL. Confirm this is the only URL change
   needed — re-check the file for any other hardcoded port before rerunning.

4. **Run it, then actually look at the results** — not just the pass/fail
   count. The script takes screenshots at each step (per its own docstring:
   regression check, rank-mismatch dimming, rejected-play toast, cancel
   flow, hand throw, face-up throw). Open and look at each screenshot.
   A green assertion doesn't confirm the UI *looks* right — dimming that's
   technically `opacity: 0.45` per the CSS class could still be visually
   wrong (e.g. covered by something, wrong element, not applied at the
   size actually rendered). Report back specifically:
   - Did Vite start clean on 4173 with no errors?
   - Did every step in `multi_play_pass.py` pass?
   - Paste or describe what the screenshots actually show, not just that
     the assertions passed.

5. **If anything fails**, diagnose it — don't just retry the same command
   hoping it works. If it's a new/different error than the port and
   binding issues already fixed, say so explicitly rather than assuming
   it's the same root cause again.

## Definition of done
- Vite dev server runs cleanly on port 4173, confirmed by actual terminal
  output, not inferred from absence of an error in a truncated log.
- `multi_play_pass.py` runs against the live dev server (not a production
  build) and every step passes.
- Screenshots have been looked at and described, not just counted.
- The stray root-level `package-lock.json` is gone.
- No leftover reliance on the port-8000 static-serve workaround for normal
  development going forward — that mount stays for its original
  deployment purpose (Docker/Cloudflare Tunnel per `CLAUDE.md`), not as
  the dev-loop default.
