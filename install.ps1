# ai-infra remote installer (Windows / PowerShell).
#
#   irm https://raw.githubusercontent.com/thien06012001/ai-infra/main/install.ps1 | iex
#
# Installs the ai-infra Claude setup + Personal Knowledge Base into the CURRENT
# directory, then installs the external CLI tools (graphify, rtk). Reports exactly
# what was installed, overwritten, appended, skipped, or failed.
#
# Env overrides: $env:AI_INFRA_TARGET, $env:AI_INFRA_MODE (override|append|skip),
#   $env:AI_INFRA_REF, $env:AI_INFRA_SRC (local payload dir), $env:AI_INFRA_SKIP_TOOLS=1
$ErrorActionPreference = 'Stop'

$Repo   = 'thien06012001/ai-infra'
$Ref    = if ($env:AI_INFRA_REF)    { $env:AI_INFRA_REF }    else { 'main' }
$Target = if ($env:AI_INFRA_TARGET) { $env:AI_INFRA_TARGET } else { (Get-Location).Path }
$Mode   = $env:AI_INFRA_MODE

function Step($m){ Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)  { Write-Host "  + $m" -ForegroundColor Green }
function Warn($m){ Write-Host "  ! $m" -ForegroundColor Yellow }
function Err($m) { Write-Host "  x $m" -ForegroundColor Red }

$Installed=@(); $Overwrote=@(); $Appended=@(); $Skipped=@(); $Kept=@(); $Failed=@()
$ToolsOk=@(); $ToolsFail=@(); $WireOk=@(); $WireFail=@()

$PayloadPaths = @('CLAUDE.md','program.md','pyproject.toml','uv.lock','.mcp.json',
  '.gitignore','.gitattributes','setup.sh','.claude','hooks','scripts','.githooks',
  'docs','knowledge','daily','reports')

Write-Host "ai-infra installer ($Repo@$Ref -> $Target)" -ForegroundColor White
Write-Host ""

# ---------- 1. obtain payload ----------
$Tmp = $null
try {
  if ($env:AI_INFRA_SRC) {
    $Src = $env:AI_INFRA_SRC
    Step "Using local payload: $Src"
    if (-not (Test-Path $Src -PathType Container)) { Err "AI_INFRA_SRC '$Src' is not a directory"; exit 1 }
  } else {
    Step "Downloading ai-infra ($Ref)"
    $Tmp = Join-Path ([IO.Path]::GetTempPath()) ("ai-infra-" + [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $Tmp | Out-Null
    $zip = Join-Path $Tmp 'src.zip'
    try {
      Invoke-WebRequest -UseBasicParsing -Uri "https://codeload.github.com/$Repo/zip/refs/heads/$Ref" -OutFile $zip
      Expand-Archive -Path $zip -DestinationPath $Tmp -Force
      $Src = Join-Path $Tmp (((Split-Path $Repo -Leaf)) + "-$Ref")
      if (-not (Test-Path $Src)) { $Src = (Get-ChildItem $Tmp -Directory | Select-Object -First 1).FullName }
      Ok "downloaded + extracted"
    } catch { Err "download failed (is the repo public and ref '$Ref' valid?)"; exit 1 }
  }
  if (-not (Test-Path $Src)) { Err "payload not found after fetch"; exit 1 }

  # ---------- 2. enumerate files (relative paths) ----------
  $files = @()
  foreach ($p in $PayloadPaths) {
    $full = Join-Path $Src $p
    if (-not (Test-Path $full)) { continue }
    if (Test-Path $full -PathType Container) {
      Get-ChildItem $full -Recurse -File | ForEach-Object {
        $files += $_.FullName.Substring($Src.Length).TrimStart('\','/')
      }
    } else { $files += $p }
  }
  if ($files.Count -eq 0) { Err "payload is empty — nothing to install"; exit 1 }

  # ---------- 3. detect conflicts + choose mode ----------
  $conflicts = ($files | Where-Object { Test-Path (Join-Path $Target $_) }).Count
  if ($conflicts -gt 0 -and -not $Mode) {
    Write-Host ""
    Write-Host "$conflicts file(s) already exist in the target. How should they be handled?" -ForegroundColor Yellow
    Write-Host "  1) override  — back up each to <name>.<timestamp>.bak, then write the infra version"
    Write-Host "  2) append    — add infra content onto existing TEXT files (others are kept untouched)"
    Write-Host "  3) skip      — keep every existing file as-is"
    $ans = Read-Host "Choose [1/2/3] (default 1)"
    switch ($ans) { '2' { $Mode='append' } '3' { $Mode='skip' } default { $Mode='override' } }
  }
  if (-not $Mode) { $Mode = 'override' }
  if ($conflicts -gt 0) { Step "Conflict mode: $Mode" }

  # ---------- 4. install files ----------
  $ts = Get-Date -Format 'yyyyMMdd-HHmmss'
  function Is-Text($rel){ $rel -match '\.(md|txt)$' -or $rel -match '(^|[\\/])\.gitignore$' -or $rel -match '(^|[\\/])\.gitattributes$' }

  Step "Installing $($files.Count) file(s) into $Target"
  foreach ($rel in $files) {
    $s = Join-Path $Src $rel; $d = Join-Path $Target $rel
    try {
      if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Force -Path (Split-Path $d -Parent) | Out-Null
        Copy-Item $s $d -Force; $Installed += $rel; continue
      }
      switch ($Mode) {
        'override' { Copy-Item $d "$d.$ts.bak" -Force; Copy-Item $s $d -Force; $Overwrote += $rel }
        'append'   {
          if (Is-Text $rel) {
            $sep = if ($rel -match '\.(gitignore|gitattributes)$') { "`n# --- added by ai-infra ---`n" } else { "`n<!-- added by ai-infra -->`n" }
            Add-Content -Path $d -Value ($sep + (Get-Content $s -Raw)); $Appended += $rel
          } else { $Kept += $rel }
        }
        'skip'     { $Skipped += $rel }
      }
    } catch { $Failed += $rel; Err "failed: $rel" }
  }
  Ok "files done"

  # ---------- 5. wire ----------
  Step "Wiring the project"
  if (Get-Command git -ErrorAction SilentlyContinue) {
    git -C $Target rev-parse --git-dir 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { git -C $Target init -q }
    git -C $Target config core.hooksPath .githooks | Out-Null
    if ($LASTEXITCODE -eq 0) { $WireOk += "git hooksPath -> .githooks" } else { $WireFail += "git hooksPath" }
  } else { $WireFail += "git not found — skipped hooksPath" }
  if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv --directory $Target sync 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $WireOk += "uv sync" } else { $WireFail += "uv sync" }
    uv run --directory $Target python scripts/index.py 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $WireOk += "knowledge index" } else { $WireFail += "knowledge index" }
  } else { $WireFail += "uv not found — skipped sync + index (https://docs.astral.sh/uv/)" }
  $WireOk   | ForEach-Object { Ok $_ }
  $WireFail | ForEach-Object { Warn $_ }

  # ---------- 6. external tools ----------
  if ($env:AI_INFRA_SKIP_TOOLS -eq '1') {
    Step "Skipping external tools (AI_INFRA_SKIP_TOOLS=1)"
  } else {
    Step "Installing external tools (graphify, rtk)"
    if (Get-Command uv -ErrorAction SilentlyContinue) {
      uv tool upgrade graphifyy 2>$null | Out-Null
      if ($LASTEXITCODE -ne 0) { uv tool install graphifyy 2>$null | Out-Null }
      if ($LASTEXITCODE -eq 0) {
        $ToolsOk += "graphify (uv tool)"
        if (Get-Command graphify -ErrorAction SilentlyContinue) {
          graphify install --platform claude 2>$null | Out-Null
          if ($LASTEXITCODE -eq 0) { $ToolsOk += "graphify claude skill" } else { $ToolsFail += "graphify claude skill" }
        }
      } else { $ToolsFail += "graphify (uv tool)" }
    } else { $ToolsFail += "graphify — uv not found" }
    # rtk ships a POSIX installer; run it via a shell if one is available (Git Bash / WSL).
    $sh = Get-Command sh -ErrorAction SilentlyContinue
    if ($sh) {
      & $sh.Source -c "curl -fsSL https://raw.githubusercontent.com/rtk-ai/rtk/develop/install.sh | sh" 2>$null | Out-Null
      if ($LASTEXITCODE -eq 0) { $ToolsOk += "rtk" } else { $ToolsFail += "rtk" }
    } else { $ToolsFail += "rtk — needs Git Bash or WSL (no POSIX shell found); install manually from github.com/rtk-ai/rtk" }
    $ToolsOk   | ForEach-Object { Ok $_ }
    $ToolsFail | ForEach-Object { Err $_ }
  }

  # ---------- 7. report ----------
  Write-Host ""
  Write-Host "──────── ai-infra install summary ────────" -ForegroundColor White
  Write-Host ("  installed:  {0}" -f $Installed.Count)
  Write-Host ("  overwrote:  {0}{1}" -f $Overwrote.Count, $(if ($Overwrote.Count -gt 0) { "  (backups: *.$ts.bak)" } else { "" }))
  Write-Host ("  appended:   {0}" -f $Appended.Count)
  Write-Host ("  skipped:    {0}" -f $Skipped.Count)
  if ($Kept.Count -gt 0) { Write-Host ("  kept(*):    {0}   (not text-appendable; left untouched)" -f $Kept.Count) }
  Write-Host ""
  Write-Host "  tools:" -ForegroundColor White; $ToolsOk | ForEach-Object { Write-Host "      $_" }
  if ($ToolsFail.Count -gt 0) { Write-Host "  tools failed:" -ForegroundColor Red; $ToolsFail | ForEach-Object { Write-Host "      $_" } }
  if ($WireFail.Count -gt 0)  { Write-Host "  wiring warnings:" -ForegroundColor Yellow; $WireFail | ForEach-Object { Write-Host "      $_" } }

  if ($Failed.Count -gt 0) {
    Write-Host ""; Write-Host ("  {0} file(s) FAILED to install:" -f $Failed.Count) -ForegroundColor Red
    $Failed | ForEach-Object { Write-Host "      $_" }
    Write-Host ""; Err "Install finished with errors."; exit 1
  }
  Write-Host ""
  Ok "ai-infra installed. Open this project in Claude Code — .claude/settings.json is live."
}
finally { if ($Tmp -and (Test-Path $Tmp)) { Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue } }
