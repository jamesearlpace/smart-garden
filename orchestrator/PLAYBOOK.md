# Playbook: Copilot-orchestrated Codex with a browser, in an outer loop

How to make **GitHub Copilot (VS Code)** kick off **OpenAI Codex CLI** to work
autonomously for a long time on a **web app** — Codex drives its own browser, audits
+ fixes + deploys in a loop, and reports a machine-readable verdict so the loop knows
when to stop. Worked example: the smart-garden sprinkler site. This doc is the
reproducible recipe + every gotcha learned building it on 2026-07-10.

---

## When to use this
- You want Codex to grind on an open-ended "find and fix bugs / improve UX" task for
  hours without you re-prompting.
- The work needs **eyes on a running website** (visual/UX/data-accuracy), not just code.
- You want to maximize a Codex subscription by keeping it working constantly.

## When NOT to use it
- One-off, well-scoped fixes (just prompt Codex once).
- Subjective polish with no objective stop condition (it never converges).
- Untrusted code (this uses `danger-full-access` — see gotcha #7).

---

## Architecture
```
Copilot (or you) launches:
  run-codex-loop.ps1  --loop-->  codex exec (FRESH session each iteration)
       ^                              | reads iterate-prompt.txt (via stdin file-redirect)
       | parse verdict JSON           | uses Playwright MCP browser (authenticated)
       | (--output-schema)            | audits a page, fixes high/med, commits + deploys
       +-----------<------------------+ returns JSON verdict
  Stop when: work_remaining=false  OR  MaxIterations  OR  MaxMinutes.
```
**Key idea:** many short *fresh* `codex exec` calls, NOT one long session. Each call
re-reads an externalized backlog file (UX-AUDIT.md). This sidesteps context-compaction
rot (a single long Codex session hit 83M tokens and started thrashing).

---

## Reproduce it from scratch

### 1. Give Codex its own browser (Playwright MCP)
Codex CLI has **no browser by default** ("browser/JavaScript runtime unavailable") and
**cannot** borrow Copilot's browser tools — different process/agent. Wire one in:
```powershell
npx -y playwright install chromium
codex mcp add playwright -- cmd /c npx -y "@playwright/mcp@latest" --headless --isolated --storage-state C:/path/.mcp-auth/storage-state.json
codex mcp list           # verify
```
Verify Codex can drive it:
```powershell
codex exec --skip-git-repo-check "Use the Playwright MCP browser to open <url> and report the <title>."
```

### 2. Authenticate (if the site is behind login)
Playwright starts with a clean profile -> lands on the login page. If the app uses a
signed session cookie, **mint one** and hand Codex a Playwright storage-state:
- Read the app's cookie scheme (e.g. `email|ts|HMAC(SESSION_SECRET,"email|ts")`).
- On the server, read `SESSION_SECRET` from the running process env
  (`/proc/<pid>/environ`) + an allowed identity; compute the token; write a Playwright
  storage-state JSON (`{cookies:[{name,value,domain,path,expires,httpOnly,secure}]}`).
- Store it OUTSIDE git (it's a real credential). Note its expiry.
- Validate without a browser: `curl --cookie "session=<tok>" <protected-url>` -> 200.
- Point the MCP at it with `--storage-state`. See `mint_session_state.py`.

### 3. Build the outer loop
Three files (see this folder):
- `iterate-prompt.txt` — one bounded iteration's instructions (browse -> find -> fix
  high/med -> verify -> commit -> deploy -> emit verdict). Bake in the safety scope.
- `verdict-schema.json` — the `--output-schema` shape the loop parses.
- `run-codex-loop.ps1` — calls `codex exec` per iteration, parses the verdict, logs,
  stops on `work_remaining=false` or caps.

### 4. Prove before you trust
Run `-MaxIterations 3` first. Verify against the success checklist below. Only scale to
a long run once a short run behaves.

---

## GOTCHAS / LEARNINGS (the important part)

1. **Codex CLI has no browser; can't use Copilot's.** They're separate agents. Give
   Codex its own via Playwright MCP.
2. **`--storage-state` is ignored without `--isolated`.** In default persistent-profile
   mode Playwright MCP ignores the storage-state and you land on Login. Add `--isolated`.
3. **Site auth has no LAN bypass** (check `check_auth`); mint the signed cookie from the
   server's live `SESSION_SECRET`. The cookie is a 30-day credential -> gitignore it,
   track expiry, refresh with the mint script.
4. **Passing a multi-line prompt to `codex exec` from PowerShell:**
   - Passing as an argument -> PowerShell/wrapper **word-splits** it ("unexpected
     argument 'Garden'").
   - Piping `$prompt | codex exec -` **hangs** under `powershell -File` (no stdin EOF).
   - **WORKS:** `cmd /c "codex exec ... - < promptfile"` — file redirect gives a clean EOF.
5. **`$ErrorActionPreference = "Stop"` + `2>&1` aborts the loop.** Codex prints its
   version banner to stderr; `2>&1` surfaces it as a PowerShell error record, which under
   `Stop` throws and kills the script right after the codex call. **Fix:** keep `2>&1`
   INSIDE the `cmd /c "... 2>&1"` string, and set `$ErrorActionPreference='Continue'`
   around the call.
6. **`--sandbox workspace-write` CANCELS the Playwright browser.** Chromium needs
   out-of-workspace file + network access; workspace-write blocks it -> "browser call
   was canceled." **Fix:** `--sandbox danger-full-access`.
7. **`danger-full-access` = no sandbox safety.** Safety then comes ONLY from the prompt
   (display-only scope, "never touch <dangerous> code") + caps + per-commit checkpoints.
   Fine for your own app on your own machine; never point it at untrusted code.
8. **Fresh `codex exec` per iteration beats `resume`.** One long session compacts and
   rots (forgets what it checked, re-audits, thrashes). Fresh calls + an externalized
   backlog file it re-reads each time stay sharp.
9. **`--output-schema` makes the loop possible.** Forcing a JSON verdict
   (`work_remaining`, counts, summary) gives the loop an objective stop signal.
10. **Async launch cwd differs.** A backgrounded `powershell -File` may start in a
    different directory — use an ABSOLUTE `-File` path; have the script `Set-Location`
    its own repo.
11. **Keep `.ps1` pure ASCII.** Em-dashes/smart-quotes get mis-encoded and break the
    parser ("string missing terminator"). Use `-` and straight quotes only.
12. **Prove with a short run.** Every failed 3-iteration run above taught exactly one
    gotcha (4, 5, 6). Cheap to catch early; expensive if it's a 4-hour unattended run.

---

## How to measure success (verify, do NOT trust the verdict)
Codex saying `work_remaining=false` is a claim, not proof (guard against the false-done
pattern). Check:
1. **Mechanics:** every `iter-NNN.json` valid + schema-conformant; `loop-log.md` has a
   line per iteration; loop re-invoked N times; each summary names a real page (browser
   was authenticated, not Login).
2. **Real + safe:** `git log` shows commits matching `fixed_this_iter`; a sampled
   "fixed" item verifies as genuinely fixed on the live site; **`git diff` across loop
   commits touches ZERO dangerous/out-of-scope code** (else abort + rollback); no
   regressions; server<->git parity.
3. **Honest done-signal:** `work_remaining=false` on iter 1 with 0 fixes = red flag,
   re-audit to confirm; healthy = early passes find issues and convert them to commits.

---

## Reuse checklist for a new project
- [ ] Playwright MCP added to Codex; `--isolated`; browser test returns the real title.
- [ ] Auth handled (storage-state minted + gitignored) if the app needs login.
- [ ] `iterate-prompt.txt` written with the project's safety scope + "don't touch X".
- [ ] `verdict-schema.json` fields match your stop condition.
- [ ] `run-codex-loop.ps1`: `cmd /c "codex exec --sandbox danger-full-access
      --output-schema ... -o ... - < prompt 2>&1"`, `ErrorActionPreference` guarded.
- [ ] 3-iteration proving run passes the success checklist.
- [ ] Only then scale `-MaxIterations` / `-MaxMinutes`.
