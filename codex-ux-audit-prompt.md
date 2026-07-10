# Smart-Garden UX Audit — Codex driver prompt

One-line reuse: **"Continue the smart-garden UX audit per codex-ux-audit-prompt.md."**

Run at **Extra High** reasoning, in a **git worktree**, with **working browser access**
(verify the browser can load a page in the first 5 minutes before committing to the run).

---

## The prompt (paste this)

```
ROLE: Long autonomous session improving the smart-garden sprinkler website's bugs
and usability. Work in two phases. Do NOT ask me what to do next — generate your
own work from the audit. Set reasoning effort to Extra High.

FIRST, verify you actually have a working browser: open one page of the site and
confirm you can see it and read its console. If you cannot drive a browser, STOP
and tell me — do not fall back to code-only guessing.

HARD SAFETY SCOPE (never cross):
- DISPLAY / USABILITY only. Do NOT change watering behavior: no edits to valve
  control, MAD, runtimes, precip rates, schedule generation, config.yaml watering
  params, or the irrigation engine. If something is actually WRONG WATERING
  BEHAVIOR (not a display bug), LOG it under a "Watering-behavior (DO NOT FIX)"
  section and move on.
- Back up before any deploy. Diff server vs local before AND after deploy; server
  and git must agree at the end. Put ssh/shell logic in scripts, not inline bash.
- No bypassing safety checks. No force-push, no --no-verify.

READ FIRST:
- smart-garden-journey.md in full, incl. any "don't re-propose / dead-ends" list.
- AGENTS.md and repo conventions.
- Enumerate EVERY user-facing route from dashboard.py (not just template names).

=== PHASE 1 — AUDIT ONLY (no code changes) ===
Do exactly one structured pass and write findings into UX-AUDIT.md. Change no code.
For each page, at BOTH desktop and mobile viewports:
- Click every control; record any console errors/warnings.
- CROSS-CHECK displayed values against the underlying API/DB — flag anything where
  the screen disagrees with the source of truth (this is the priority).
- Check empty / loading / error states, not just the happy path.
Log each finding to UX-AUDIT.md as a row: page | severity (high/med/low) | category
| expected vs actual | proposed fix. Triage severity honestly.
When the pass is complete, STOP and post me a summary of the findings table.
(If I'm not around, proceed to Phase 2 automatically — but Phase 1 must be fully
written to UX-AUDIT.md first.)

=== PHASE 2 — FIX IN BOUNDED BATCHES ===
- Fix ONLY high and medium findings. Ignore all "low" (that is the done floor).
- Work ONE PAGE at a time. Before each page, re-read UX-AUDIT.md (do not trust
  memory — the context may have compacted).
- For each fix: verify in the browser (reload, re-click, re-check console + data),
  commit (git checkpoint), deploy, re-verify LIVE, diff parity, mark resolved.
- Hard stop when every high/med item is resolved. Do NOT invent new low-priority
  polish. Do NOT start a third open-ended pass.

<verification>
- Never mark a finding fixed without re-checking it in the browser.
- Don't hand back until every high/med item in UX-AUDIT.md is resolved and verified.
</verification>

WHEN FINISHED: update smart-garden-journey.md with a dated entry; leave UX-AUDIT.md
as the record; give me: the findings table, everything fixed, everything LOGGED as
watering-behavior (not fixed), and the remaining low-priority items.
```

---

## Why two phases (not an infinite loop)
- Codex **auto-compacts** on long runs and loses track of what it already checked;
  the audit-first pass + re-reading UX-AUDIT.md each item is the externalized memory
  that survives compaction.
- "Fix high/med, ignore low" is a **real done-condition** — an open-ended
  "loop until clean" never converges on subjective UX and risks over-polishing +
  regressions on a live system.
- Audit-before-fix gives a **triaged list you can trust** before it changes many
  files unsupervised.

## Pages to cover (verify routes in dashboard.py)
Main: dashboard/index, moisture_sim, water_usage, forecast_merged, flow, map,
sensor_history, costs, convergence, cnn_report, login.
Meter/camera diagnostics: cam_hub, cam_archive, cam_review, cam_reading, cam_labels,
cam_quality, cam_regression, cam_device, cam_focus, cam_testaudit.
