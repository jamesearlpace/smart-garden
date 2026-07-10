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

---

## Architecture options (2026-07-10) — and which to pick
Three levels of sophistication, in increasing order of build cost:
- **A. Single worker, angle-rotating prompt.** The proven `run-codex-loop.ps1` but the
  prompt tells ONE agent to rotate lenses (functional -> perf -> data-accuracy -> RCA) and
  self-critique. Cheapest, least failure surface. ~70% of the variety benefit.
- **B. Sequential director + worker.** A planner agent generates one campaign, a worker
  runs it. Better variety enforcement, but NO parallelism -> it pays multi-agent
  complexity without the parallelism that justifies multi-agent. **Least attractive.**
- **C. Director + PARALLEL read-only audit + SERIAL fix (`run-director-parallel.ps1`).**
  Director emits 3-6 independent audit campaigns; they run CONCURRENTLY (background jobs),
  each read-only (browse + write own `findings-N.json`, no repo writes -> safe to
  parallelize); then ONE serial fixer merges findings + fixes high/med one at a time
  (serial -> no git/deploy races). **This is the one to build for a single deploy target.**
  Key principle: **parallelize the read-only phase, serialize the write/deploy phase.**

## Research grounding (2026-07-10) — is anyone else doing this?
Yes; it is a named, frontier pattern. Sources read:
- **Anthropic "Building Effective Agents"** — names *evaluator-optimizer* (my director+verdict)
  and *orchestrator-workers* (director+workers); agents = LLMs+tools in a loop with explicit
  stopping conditions. Endorses exactly this shape.
- **Anthropic "How we built our multi-agent research system"** — a LEAD agent spawns
  subagents to explore different aspects in parallel, then synthesizes and refines. Findings:
  multi-agent beat single-agent by 90% on breadth-first tasks; **token usage alone explained
  80% of performance variance** (so "cost no object -> more spend buys thoroughness" is real);
  BUT ~15x the tokens of a chat, and **coding is a WEAKER fit than research** (fewer
  parallelizable subtasks, coordination is hard). "Teach the orchestrator to delegate"
  (specific bounded prompts) and "start wide then narrow."
- **Lilian Weng "LLM Powered Autonomous Agents"** — BabyAGI (task-generating agent that
  creates new tasks from prior results = the director), AutoGPT (self-critique + spawns
  sub-agents), Reflexion / Self-Refine (the "look again, did you consider X" loop),
  HuggingGPT (LLM planner decomposes + dispatches), Generative Agents (reflection: "generate
  the salient questions, then answer them").
- **Simon Willison / community** — Codex has a native `/goal` (the "Ralph loop") that loops
  to a goal until done or budget exhausted. Cost cautions: Uber capped AI spend at $1.5K/mo
  after blowout; James Shore's maintenance-cost math; Geoffrey Litt's "cognitive debt";
  "tokenmaxxing" viewed skeptically. Consensus healthy frame: **it's your loop you invite
  agents into** — measure *verified value shipped*, not hours/tokens burned.

## Safety under danger-full-access — the borderline lesson (2026-07-10)
- The parallel run's fixer edited `server-prod/database.py` (a control-ADJACENT backend
  file). On inspection it only touched `get_forecast_vs_actual` / `get_forecast_accuracy_summary`
  (READ/reporting functions that compute a displayed score) — NOT the irrigation
  balance/credit (`irrigation_mm`) or scheduling. So it was a legit display-accuracy fix.
- LESSON: `danger-full-access` means the guardrail is the PROMPT, not a wall. A future RCA
  *could* edit control logic. Mitigation applied: the fix-prompt now says reporting/display
  queries MAY be edited but balance/credit/scheduling functions NEVER, stop-and-log if a fix
  needs control changes, and name+justify any backend `.py` edit. The success checklist's
  "`git diff` touches zero control code" gate is what catches a violation.

## Running it on a home server (FUTURE consideration, 2026-07-10 — not done)
Goal: run the loop on the NUC so closing the laptop doesn't stop it. It's a PORT, not a copy
(servers are Linux; this stack is Windows/PowerShell/cmd). Chosen target: **NUC
(192.168.0.157)** — beefier (i7, 30GB), won't compete with the live site on the Acer;
deploys to Acer over ssh (as the script already does). Port checklist:
- [ ] Codex CLI installed + AUTHENTICATED on the NUC (the friction: copy `~/.codex/auth.json`
      + `config.toml` from laptop, OR `codex login` device-code flow — needs James's hands).
- [ ] Playwright MCP + `npx playwright install chromium` on Linux (headless works well).
- [ ] Copy `.mcp-auth/storage-state.json` (or run `mint_session_state.py` on the NUC).
- [ ] Clone `jamesearlpace/smart-garden` on the NUC; confirm NUC can `ssh acer` to deploy.
- [ ] Port the `.ps1` orchestrator to **bash** (replace `cmd /c "... < f 2>&1"` with plain
      `codex exec ... < f 2>&1`; Start-Job -> `&` background + `wait`). Re-test the harness.
- [ ] Run under **tmux** or a **systemd** unit so it survives SSH/laptop disconnect.
- NOTE: NUC ssh was flaky during recon ("Connection reset") — verify stable access first.
