# Resume: declutter the table (previous session hit its usage limit mid-investigation)

A prior session on this exact task got cut off by a usage limit before any
edits were made — it had only just finished checking things, no code
changed yet. Full spec is still `docs/phase-prompts/declutter-table-and-felt.md`
— read that first, it's the real task. This file only carries forward what
was already confirmed, so you don't have to re-derive it:

- `frontend/src/assets/table/table-frame.png` exists — Task 4 is in play,
  not the fallback path.
- **Correction to the original spec:** it warned the PNG's interior was
  solid white and would need masking/a dark scrim to hide it. That was
  wrong — the previous session checked the actual alpha channel
  (`Image.open(...).convert('RGBA')`, sampled the interior region) and
  found it's genuinely transparent: 0 opaque samples out of 500 checked
  inside the oval. So the interior does NOT need masking or a blend-mode
  trick — it can be used more directly as a frame, with the dark felt
  color from Task 3 showing through the already-transparent center
  naturally. Don't redo this check, it's confirmed; just build with it.
- CSS variables and the current seat/ring structure in `App.css` and
  `GameScreen.jsx` had already been read but not yet changed — start fresh
  from the real files, nothing there is stale.

Proceed straight to implementing Tasks 1–4 from the main spec doc. Same
"before you're done" checklist and deploy step apply — nothing about the
finish line changed, only the interior-transparency fact above.
