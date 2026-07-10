<#
  Codex outer-loop orchestrator for the smart-garden UX audit.

  Runs `codex exec` repeatedly (fresh session each time = no context rot). Each
  iteration re-reads UX-AUDIT.md, audits/fixes a bounded chunk, and returns a JSON
  verdict (verdict-schema.json). The loop stops when Codex reports work_remaining
  = false, or a safety cap is hit.

  Usage:
    .\orchestrator\run-codex-loop.ps1                    # defaults: 20 iters / 240 min
    .\orchestrator\run-codex-loop.ps1 -MaxIterations 8 -MaxMinutes 90
    .\orchestrator\run-codex-loop.ps1 -DryRun            # print the plan, don't run

  Stop it anytime with Ctrl+C. Each iteration commits/deploys its own work, so
  stopping mid-loop leaves a clean, revertible state.
#>
param(
  [int]$MaxIterations = 20,
  [int]$MaxMinutes = 240,
  [string]$Repo = "C:\MyCode\smart-garden",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
Set-Location $Repo
$orch      = Join-Path $Repo "orchestrator"
$schema    = Join-Path $orch "verdict-schema.json"
$promptTxt = Join-Path $orch "iterate-prompt.txt"
$logFile   = Join-Path $orch "loop-log.md"
$prompt    = Get-Content $promptTxt -Raw

if (-not (Test-Path $logFile)) {
  "# Codex loop log`n" | Set-Content $logFile
}
$start = Get-Date
Add-Content $logFile "`n## Run started $($start.ToString('u')) (max $MaxIterations iters / $MaxMinutes min)"

if ($DryRun) {
  Write-Host "DRY RUN - would run up to $MaxIterations iterations, $MaxMinutes min cap."
  Write-Host 'Per iter: codex exec --skip-git-repo-check --sandbox workspace-write --output-schema <schema.json> -o <iter.json> <prompt>'
  return
}

for ($i = 1; $i -le $MaxIterations; $i++) {
  $elapsed = ((Get-Date) - $start).TotalMinutes
  if ($elapsed -ge $MaxMinutes) {
    Add-Content $logFile "- STOP: time cap ($MaxMinutes min) reached at iter $i."
    Write-Host "Time cap reached. Stopping."
    break
  }

  $outJson = Join-Path $orch ("iter-{0:D3}.json" -f $i)
  Write-Host "=== Iteration $i (elapsed $([int]$elapsed) min) ===" -ForegroundColor Cyan

  # Fresh codex exec each iteration: small context, re-reads UX-AUDIT.md.
  # Prompt via file-redirect through cmd /c (gives codex a proper stdin EOF;
  # piping via PowerShell hangs under -File). Keep 2>&1 INSIDE cmd so codex's
  # stderr banner is not surfaced as a PowerShell error (which would trip
  # ErrorActionPreference=Stop and abort the loop).
  $prevEAP = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  cmd /c "codex exec --skip-git-repo-check --sandbox danger-full-access --output-schema `"$schema`" -o `"$outJson`" - < `"$promptTxt`" 2>&1" | Out-Null
  $ErrorActionPreference = $prevEAP

  if (-not (Test-Path $outJson)) {
    Add-Content $logFile "- iter $i : NO verdict file produced - stopping (check codex auth/errors)."
    Write-Host "No verdict produced. Stopping." -ForegroundColor Yellow
    break
  }

  try {
    $v = Get-Content $outJson -Raw | ConvertFrom-Json
  } catch {
    Add-Content $logFile "- iter $i : verdict not valid JSON - stopping."
    Write-Host "Verdict not valid JSON. Stopping." -ForegroundColor Yellow
    break
  }

  $stamp = (Get-Date).ToString('u')
  Add-Content $logFile ("- iter {0} [{1}]: high_med_open={2} new={3} fixed={4} deployed={5} - {6}" -f `
    $i, $stamp, $v.high_med_open, $v.new_findings_this_pass, $v.fixed_this_iter, $v.deployed, $v.summary)
  Write-Host ("  open(high/med)={0}  new={1}  fixed={2}  -> {3}" -f `
    $v.high_med_open, $v.new_findings_this_pass, $v.fixed_this_iter, $v.summary)

  if (-not $v.work_remaining) {
    Add-Content $logFile "- DONE: Codex reports no work remaining at iter $i."
    Write-Host "Codex reports no work remaining. Loop complete." -ForegroundColor Green
    break
  }
}

$mins = [int]((Get-Date) - $start).TotalMinutes
Add-Content $logFile "## Run ended $((Get-Date).ToString('u')) - $mins min total"
Write-Host "Loop finished after $mins min. Log: $logFile" -ForegroundColor Green

