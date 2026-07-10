# Codex Outer-Loop Orchestrator (smart-garden UX)

Runs OpenAI **Codex** in a constant loop to audit + fix the smart-garden sprinkler
website, so it keeps working without a human re-prompting each time. Built 2026-07-10.

## Why this exists
A single Codex session runs short (empties its backlog, then stops) and rots after
context compaction on long runs. This orchestrator flips it: **many short, fresh
`codex exec` calls** instead of one long session. Each call re-reads the backlog,
does a bounded chunk, and reports a machine-readable verdict. The loop provides the
persistence; each Codex call stays small and sharp.

## How it works
```
run-codex-loop.ps1  ──loop──►  codex exec (fresh session each time)
     ▲                              │  reads iterate-prompt.txt
     │  parse verdict JSON          │  uses Playwright MCP browser (authenticated)
     │  (verdict-schema.json)       │  audits a page, fixes high/med, commits+deploys
     └──────────────◄───────────────┘  returns JSON verdict (--output-schema)
Stop when: work_remaining=false  OR  MaxIterations  OR  MaxMinutes cap.
```

### Files
| File | Purpose |
|------|---------|
| `run-codex-loop.ps1` | The loop. Calls `codex exec` per iteration, parses the verdict, logs, stops on done/cap. |
| `iterate-prompt.txt` | Per-iteration instructions (browse → find → fix high/med → verify → commit → deploy → verdict). Display-only safety scope baked in. |
| `verdict-schema.json` | `--output-schema` shape: `work_remaining, high_med_open, new_findings_this_pass, fixed_this_iter, deployed, summary`. |
| `loop-log.md` | One line per iteration (gitignored). |
| `iter-NNN.json` | Per-iteration verdict (gitignored). |

Depends on: the `playwright` Codex MCP (headless, isolated, pre-authenticated) and the
minted session cookie at `../.mcp-auth/storage-state.json` (see repo memory
`smart-garden-codex-browser.md`). Backlog lives in `../UX-AUDIT.md`.

## Run it
```powershell
cd C:\MyCode\smart-garden
.\orchestrator\run-codex-loop.ps1 -DryRun                     # show the plan
.\orchestrator\run-codex-loop.ps1 -MaxIterations 3 -MaxMinutes 60   # proving run
.\orchestrator\run-codex-loop.ps1 -MaxIterations 40 -MaxMinutes 480 # long run
```
Ctrl+C anytime — each iteration commits/deploys its own work, so stopping leaves a
clean, revertible state.

## Safety
- **Display/usability only.** The prompt forbids touching the irrigation engine,
  valves, MAD, runtimes, precip rates, schedule generation, or `config.yaml` watering
  params. Real wrong-watering behavior is logged (not fixed).
- `--sandbox workspace-write` lets Codex edit + deploy. It auto-commits and deploys to
  the live server unsupervised — the caps + per-commit checkpoints bound the blast radius.
- Cookie in `../.mcp-auth/` expires ~30 days after minting; refresh with
  `mint_session_state.py` when Codex starts landing on the Login page.

## How success is measured (verify, don't trust the verdict)
1. **Loop mechanics:** every `iter-NNN.json` is valid + schema-conformant; `loop-log.md`
   has a line per iteration; the loop re-invoked N times and exited cleanly; each
   summary names a real page (browser was authenticated, not Login).
2. **Real + safe work:** `git log` shows new commits matching `fixed_this_iter`; a
   sampled "fixed" item verifies as genuinely fixed on the live site; **`git diff`
   across loop commits touches ZERO watering-logic/config** (else abort+rollback);
   no regressions; server↔git parity holds.
3. **Honest done-signal:** `work_remaining=false` on iter 1 with 0 fixes = red flag
   (re-audit to confirm), not success. Healthy = early passes find new issues and
   convert them to commits.
