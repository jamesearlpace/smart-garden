<#
  Director + parallel-audit + serial-fix orchestrator for the smart-garden website.

  Each round:
    1. DIRECTOR (1 codex call) picks 3-6 independent, READ-ONLY audit campaigns
       (varied angles / pages) and returns them as JSON.
    2. PARALLEL AUDIT: those campaigns run concurrently as background jobs. Each is
       read-only (browses, reports findings to its own findings-N.json). No repo writes,
       no commits -> safe to parallelize.
    3. SERIAL FIX (1 codex call) merges all findings into UX-AUDIT.md and fixes every
       open high/med ONE at a time (commit + deploy + verify). Serial -> no git/deploy races.
    4. Log the round; repeat until the director says done or a cap is hit.

  This is the "parallel breadth for the safe phase, serial for the dangerous phase"
  design (see PLAYBOOK.md / the research: Anthropic multi-agent research system).

  Usage:
    .\orchestrator\run-director-parallel.ps1 -DryRun
    .\orchestrator\run-director-parallel.ps1 -MaxRounds 6 -MaxMinutes 480
  Ctrl+C to stop; each fix is committed/deployed individually so stopping is clean.
#>
param(
  [int]$MaxRounds = 6,
  [int]$MaxMinutes = 480,
  [int]$WorkerTimeoutSec = 1200,
  [int]$MaxParallel = 6,
  [string]$Repo = "C:\MyCode\smart-garden",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-Location $Repo
$orch        = Join-Path $Repo "orchestrator"
$dirSchema   = Join-Path $orch "director-batch-schema.json"
$dirPrompt   = Join-Path $orch "director-batch-prompt.txt"
$auditSchema = Join-Path $orch "audit-schema.json"
$fixSchema   = Join-Path $orch "fix-verdict-schema.json"
$fixPrompt   = Join-Path $orch "fix-prompt.txt"
$log         = Join-Path $orch "campaign-log.md"

function New-AuditPrompt([string]$angle, [string]$target, [string]$body) {
@"
You are a READ-ONLY QA auditor for the smart-garden website
(https://sprinklers.savagepace.com/). Use the playwright MCP browser (headless, already
authenticated). DO NOT edit files, commit, deploy, or change anything -- ONLY inspect and
REPORT. If a page shows "Smart Garden - Login", the session expired: say so in notes and
stop. Cross-check displayed values against the API (curl) where relevant. Check desktop AND
mobile widths, and empty/loading/error states.

CAMPAIGN (angle: $angle ; target: $target):
$body

Return ONLY JSON: { angle, target, findings:[{page,severity,category,expected_vs_actual,proposed_fix,is_watering_behavior}], notes }
severity is high|med|low. Set is_watering_behavior=true only for real irrigation-behavior
issues (not display bugs).
"@
}

if (-not (Test-Path $log)) { "# Campaign log`n" | Set-Content $log }
$start = Get-Date
$runStamp = $start.ToString('yyyyMMdd-HHmmss')
Add-Content $log "`n## Parallel director run started $($start.ToString('u')) (max $MaxRounds rounds / $MaxMinutes min)"

if ($DryRun) {
  Write-Host "DRY RUN - would run up to $MaxRounds rounds, $MaxMinutes min cap, up to $MaxParallel parallel auditors."
  Write-Host "Director -> parallel audit jobs -> serial fixer, per round."
  return
}

for ($round = 1; $round -le $MaxRounds; $round++) {
  if (((Get-Date) - $start).TotalMinutes -ge $MaxMinutes) {
    Add-Content $log "- STOP: time cap reached at round $round."; break
  }
  Write-Host "=== ROUND $round ===" -ForegroundColor Cyan

  # per-round work dir (unique names -> no cross-round file locks even if an audit orphaned)
  $roundWork = Join-Path $orch ("_work\round-{0:D2}" -f $round)
  New-Item -ItemType Directory -Force -Path $roundWork | Out-Null

  # 1. DIRECTOR
  $dirOut = Join-Path $roundWork "director-out.json"
  Remove-Item $dirOut -ErrorAction SilentlyContinue
  $prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  cmd /c "codex exec --skip-git-repo-check --sandbox danger-full-access --output-schema `"$dirSchema`" -o `"$dirOut`" - < `"$dirPrompt`" 2>&1" | Out-Null
  $ErrorActionPreference = $prevEAP
  if (-not (Test-Path $dirOut)) { Add-Content $log "- round ${round}: director produced no output - stopping."; break }
  try { $plan = Get-Content $dirOut -Raw | ConvertFrom-Json } catch { Add-Content $log "- round ${round}: director JSON invalid - stopping."; break }
  if ($plan.done) { Add-Content $log "- DONE: director reports full coverage at round $round."; Write-Host "Director reports done." -ForegroundColor Green; break }
  $campaigns = @($plan.campaigns) | Select-Object -First $MaxParallel
  if ($campaigns.Count -eq 0) { Add-Content $log "- round ${round}: no campaigns - stopping."; break }

  # 2. PARALLEL AUDIT (read-only background jobs; per-round dir avoids file locks)
  $jobs = @()
  for ($i = 0; $i -lt $campaigns.Count; $i++) {
    $c  = $campaigns[$i]
    $pf = Join-Path $roundWork ("campaign-{0}.txt" -f $i)
    (New-AuditPrompt $c.angle $c.target $c.campaign_prompt) | Set-Content $pf -Encoding ascii
    $ff = Join-Path $roundWork ("findings-{0}.json" -f $i)
    $jobs += Start-Job -ScriptBlock {
      param($repo, $schema, $ff, $pf)
      Set-Location $repo
      cmd /c "codex exec --skip-git-repo-check --sandbox danger-full-access --output-schema `"$schema`" -o `"$ff`" - < `"$pf`" 2>&1" | Out-Null
    } -ArgumentList $Repo, $auditSchema, $ff, $pf
    Write-Host ("  launched audit {0}: {1} -> {2}" -f $i, $c.angle, $c.target)
  }
  Wait-Job $jobs -Timeout $WorkerTimeoutSec | Out-Null
  $jobs | ForEach-Object { if ($_.State -eq 'Running') { Stop-Job $_ -ErrorAction SilentlyContinue }; Receive-Job $_ -ErrorAction SilentlyContinue | Out-Null; Remove-Job $_ -Force -ErrorAction SilentlyContinue }
  $foundCount = @(Get-ChildItem (Join-Path $roundWork "findings-*.json") -ErrorAction SilentlyContinue).Count
  Write-Host "  audit complete: $foundCount findings files"

  # 3. SERIAL FIX (merges this round's findings + fixes high/med one at a time)
  $fixOut = Join-Path $roundWork "fix-out.json"
  $fixInput = Join-Path $roundWork "fix-input.txt"
  ("This round's raw auditor findings are the JSON files in: $roundWork (findings-*.json). Read ALL of them.`n`n" + (Get-Content $fixPrompt -Raw)) | Set-Content $fixInput -Encoding ascii
  $prevEAP = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
  cmd /c "codex exec --skip-git-repo-check --sandbox danger-full-access --output-schema `"$fixSchema`" -o `"$fixOut`" - < `"$fixInput`" 2>&1" | Out-Null
  $ErrorActionPreference = $prevEAP
  $fx = if (Test-Path $fixOut) { try { Get-Content $fixOut -Raw | ConvertFrom-Json } catch { $null } } else { $null }

  # 4. LOG
  $stamp  = (Get-Date).ToString('u')
  $angles = (($campaigns | ForEach-Object { $_.angle }) -join ', ')
  Add-Content $log ("- round {0} [{1}]: {2} parallel audits ({3})" -f $round, $stamp, $campaigns.Count, $angles)
  if ($fx) {
    Add-Content $log ("    fix: merged={0} fixed={1} still_open={2} watering_flags={3} deployed={4} - {5}" -f $fx.merged_new_findings, $fx.fixed, $fx.still_open_high_med, $fx.watering_flags, $fx.deployed, $fx.summary)
    Write-Host ("  fix: fixed={0} still_open={1} - {2}" -f $fx.fixed, $fx.still_open_high_med, $fx.summary) -ForegroundColor Green
  } else {
    Add-Content $log "    fix: no verdict produced this round."
  }

  # 5. ARCHIVE this round's generated prompts + findings + verdict for later review
  $rd = Join-Path $orch ("runs\{0}\round-{1:D2}" -f $runStamp, $round)
  New-Item -ItemType Directory -Force -Path $rd | Out-Null
  if (Test-Path $dirOut) { Copy-Item $dirOut (Join-Path $rd "director-campaigns.json") -ErrorAction SilentlyContinue }
  Get-ChildItem (Join-Path $roundWork "findings-*.json") -ErrorAction SilentlyContinue | Copy-Item -Destination $rd -ErrorAction SilentlyContinue
  Get-ChildItem (Join-Path $roundWork "campaign-*.txt") -ErrorAction SilentlyContinue | Copy-Item -Destination $rd -ErrorAction SilentlyContinue
  if (Test-Path $fixOut) { Copy-Item $fixOut (Join-Path $rd "fix-verdict.json") -ErrorAction SilentlyContinue }
  $sum = @("# Round $round - $stamp", "", "## Director campaigns (angles + the exact prompts it generated)")
  for ($k = 0; $k -lt $campaigns.Count; $k++) {
    $cc = $campaigns[$k]
    $sum += ("### {0}. {1} -> {2}" -f ($k + 1), $cc.angle, $cc.target)
    $sum += '```'
    $sum += $cc.campaign_prompt
    $sum += '```'
  }
  if ($fx) {
    $sum += "## Fix verdict"
    $sum += ("fixed={0} still_open={1} merged={2} watering_flags={3} deployed={4}" -f $fx.fixed, $fx.still_open_high_med, $fx.merged_new_findings, $fx.watering_flags, $fx.deployed)
    $sum += $fx.summary
  }
  ($sum -join "`n") | Set-Content (Join-Path $rd "round-summary.md") -Encoding ascii
  Write-Host ("  archived -> {0}" -f $rd)
}

$mins = [int]((Get-Date) - $start).TotalMinutes
Add-Content $log "## Parallel director run ended $((Get-Date).ToString('u')) - $mins min total"
Write-Host "Director run finished after $mins min. Log: $log" -ForegroundColor Green

