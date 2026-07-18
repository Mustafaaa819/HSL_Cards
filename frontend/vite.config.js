import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // 5173 (Vite's default) falls inside a Windows Hyper-V excluded port
  // range on this machine (`netsh interface ipv4 show excludedportrange
  // protocol=tcp` — confirmed 5173-5272 is blocked, along with several
  // other nearby ranges). 4173 sits clear of all of them. This exclusion
  // list can shift on reboot, so if dev breaks again with the same
  // "exit code 1" / bind failure, re-run that netsh command before
  // assuming it's a code problem.
  server: {
    port: 4173,
    // Without this, Vite silently falls back to 4174/4175/... whenever
    // something else already holds 4173 — which is exactly what caused a
    // long, confusing debugging loop: the app "ran" on a different port
    // than the backend's CORS allowlist expected, and every request died
    // with a generic network error that looked identical to the backend
    // being down. Fail loudly instead: if this errors, something (often a
    // stale process from a previous session) is still holding the port —
    // find and kill it rather than letting Vite paper over it.
    strictPort: true,
  },
})
