# ai-infra remote installer (Windows / PowerShell).
#
#   irm https://raw.githubusercontent.com/thien06012001/ai-infra/main/install.ps1 | iex
#
# Installs the ai-infra Claude setup + Personal Knowledge Base into the CURRENT
# directory, then installs the external CLI tools (graphify, codegraph, rtk). Reports exactly
# what was installed, overwritten, appended, skipped, or failed.
#
# Env overrides: $env:AI_INFRA_NAME (project name; default: ask, else target dir name),
#   $env:AI_INFRA_TARGET, $env:AI_INFRA_MODE (override|append|skip),
#   $env:AI_INFRA_REF, $env:AI_INFRA_SRC (local payload dir), $env:AI_INFRA_SKIP_TOOLS=1,
#   $env:AI_INFRA_SKIP_PLUGINS=1 (skip installing the declared Claude plugins),
#   $env:AI_INFRA_SKIP_PREREQS=1 (skip auto-installing git, jq, node, uv),
#   $env:PLANNOTATOR_VERSION=<vX.Y.Z> (pinned plannotator binary release; default v0.22.0)
$ErrorActionPreference = 'Stop'

$Repo   = 'thien06012001/ai-infra'
$Ref    = if ($env:AI_INFRA_REF)    { $env:AI_INFRA_REF }    else { 'main' }
$Target = if ($env:AI_INFRA_TARGET) { $env:AI_INFRA_TARGET } else { (Get-Location).Path }
# Cmdlets resolve relative paths against $PWD, but [IO.File] resolves against
# [Environment]::CurrentDirectory, which PowerShell never syncs. Absolutize once
# so both agree for the rest of the run.
$Target = [IO.Path]::GetFullPath((Join-Path (Get-Location).ProviderPath $Target))
$Mode   = $env:AI_INFRA_MODE

function Step($m){ Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)  { Write-Host "  + $m" -ForegroundColor Green }
function Warn($m){ Write-Host "  ! $m" -ForegroundColor Yellow }
function Err($m) { Write-Host "  x $m" -ForegroundColor Red }

$Installed=@(); $Overwrote=@(); $Appended=@(); $Skipped=@(); $Kept=@(); $Failed=@()
$ToolsOk=@(); $ToolsFail=@(); $WireOk=@(); $WireFail=@()

# 'docs/pkb-schema.md' rather than all of 'docs': docs/superpowers/{specs,plans}
# are design records about building this template, not documentation the
# installed project needs.
$PayloadPaths = @('CLAUDE.md','program.md','pyproject.toml','uv.lock','.mcp.json',
  '.gitignore','.gitattributes','setup.sh','.claude','hooks','scripts','.githooks',
  'docs/pkb-schema.md','knowledge','daily','reports')

Write-Host "ai-infra installer ($Repo@$Ref -> $Target)" -ForegroundColor White
Write-Host ""

# ---------- 0a. project name ----------
# The payload carries the template's own identity in three files. Capture the
# name the user wants this project to have and render it during the copy, so an
# installed project never claims to be ai-infra.

# Get-NormalizedName — fold an arbitrary human name into a PEP 508-safe slug.
# Required, not cosmetic: pyproject.toml's `name` field rejects spaces and
# uppercase, and a directory called "My App" is a legitimate install target.
# Returns an empty string when no valid character survives.
function Get-NormalizedName($raw) {
  $s = $raw.ToLowerInvariant() -replace '[ _]', '-' -replace '[^a-z0-9-]', '' -replace '-{2,}', '-'
  return $s.Trim('-')
}

$RawName = $env:AI_INFRA_NAME
if (-not $RawName) {
  $DefaultName = Split-Path $Target -Leaf
  # Track whether we actually attempted the prompt: an interactive user who
  # presses Enter to accept the default also lands in "-not $RawName" below,
  # and that case must not be reported as "non-interactive".
  $Prompted = $false
  if ([Environment]::UserInteractive -and -not [Console]::IsInputRedirected) {
    $Prompted = $true
    try { $RawName = Read-Host "Project name? [$DefaultName]" } catch { $RawName = $null }
  }
  if (-not $RawName) {
    $RawName = $DefaultName
    if (-not $Prompted) { Warn "non-interactive session — project name defaulted to '$RawName'" }
  }
}

$ProjectName = Get-NormalizedName $RawName
if (-not $ProjectName) {
  Err "project name '$RawName' normalizes to empty — use letters, digits, or hyphens"
  exit 1
}
if ($ProjectName -cne $RawName) {
  Write-Host "  using project name: $ProjectName (from ""$RawName"")"
} else {
  Write-Host "  project name: $ProjectName"
}
Write-Host ""

# ---------- 0. prerequisite preflight (auto-install when missing) ----------
# git, jq, node and uv are load-bearing for a full install: git wires the
# hooksPath, jq drives the guardrail/statusline shell hooks, node runs the .cjs
# Edit/Write guard hooks (and npx launches the context7 MCP server), and uv syncs
# the env + installs graphify. When one is missing we install it — git/jq/node
# through a detected Windows package manager (winget/scoop/choco), and uv through
# its official installer. Disable all auto-install with $env:AI_INFRA_SKIP_PREREQS=1.

# Detect-PkgMgr — return the first supported Windows package manager on PATH, or
# $null. winget ships with modern Windows, so it is preferred over scoop/choco.
function Detect-PkgMgr {
  foreach ($m in @('winget','scoop','choco')) {
    if (Get-Command $m -ErrorAction SilentlyContinue) { return $m }
  }
  return $null
}

# Pkg-Name — resolve the package id that provides <cmd> for the given manager.
# Ids differ per manager (winget uses reverse-DNS ids; scoop/choco use short
# names), so each tool is mapped explicitly rather than assuming id == command.
function Pkg-Name($cmd, $mgr) {
  switch ($cmd) {
    'git'  { switch ($mgr) { 'winget' { 'Git.Git' }      default { 'git' } } }
    'jq'   { switch ($mgr) { 'winget' { 'jqlang.jq' }     default { 'jq' } } }
    'node' { switch ($mgr) { 'winget' { 'OpenJS.NodeJS' } 'scoop' { 'nodejs-lts' } default { 'nodejs' } } }
    default { $cmd }
  }
}

# Pkg-Install — install one package id with the given manager, non-interactively.
function Pkg-Install($id, $mgr) {
  switch ($mgr) {
    'winget' { winget install --id $id -e --silent --accept-source-agreements --accept-package-agreements 2>$null | Out-Null }
    'scoop'  { scoop install $id 2>$null | Out-Null }
    'choco'  { choco install $id -y 2>$null | Out-Null }
  }
}

# Ensure-Pkg — install the package providing <cmd> only when it is absent. After
# an install it refreshes this session's PATH from the machine + user scopes so a
# freshly installed tool is visible to the wiring/tools steps below.
function Ensure-Pkg($cmd, $name) {
  if (Get-Command $cmd -ErrorAction SilentlyContinue) { Ok "$name $(& $cmd --version 2>$null | Select-Object -First 1)"; return }
  $mgr = Detect-PkgMgr
  if (-not $mgr) { Warn "$name missing and no package manager (winget/scoop/choco) found — install it manually"; return }
  Step "Installing $name via $mgr"
  try { Pkg-Install (Pkg-Name $cmd $mgr) $mgr } catch {}
  $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User')
  if (Get-Command $cmd -ErrorAction SilentlyContinue) { Ok "$name installed" } else { Err "$name install failed — install it manually" }
}

# Ensure-Uv — install uv via its official installer when absent, then add its bin
# dir to this session's PATH (default target %USERPROFILE%\.local\bin) so the
# wiring/tools steps can see it without a shell restart.
function Ensure-Uv {
  if (Get-Command uv -ErrorAction SilentlyContinue) { Ok "uv $(uv --version 2>$null)"; return }
  Step "Installing uv (astral.sh official installer)"
  try { powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex" 2>$null | Out-Null } catch {}
  $uvbin = Join-Path $env:USERPROFILE '.local\bin'
  if (Test-Path (Join-Path $uvbin 'uv.exe')) { $env:Path = "$uvbin;$env:Path" }
  if (Get-Command uv -ErrorAction SilentlyContinue) { Ok "uv installed" } else { Err "uv install failed — install from https://docs.astral.sh/uv/" }
}

if ($env:AI_INFRA_SKIP_PREREQS -eq '1') {
  Step "Skipping prerequisite auto-install (AI_INFRA_SKIP_PREREQS=1)"
} else {
  Step "Checking prerequisites (git, jq, node, uv)"
  Ensure-Pkg 'git'  'git'
  Ensure-Pkg 'jq'   'jq'
  Ensure-Pkg 'node' 'node'
  Ensure-Uv
}
Write-Host ""

# ---------- 1. obtain payload ----------
$Tmp = $null
try {
  if ($env:AI_INFRA_SRC) {
    $Src = $env:AI_INFRA_SRC
    Step "Using local payload: $Src"
    if (-not (Test-Path $Src -PathType Container)) { Err "AI_INFRA_SRC '$Src' is not a directory"; exit 1 }
    # Same $PWD vs [Environment]::CurrentDirectory divergence as $Target above:
    # absolutize now that we know the path exists, so [IO.File] calls below agree.
    $Src = (Resolve-Path -LiteralPath $Src).ProviderPath
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

  # Test-Templated — true for the three payload files carrying {{PROJECT_NAME}}.
  # An explicit allowlist rather than a blanket pass: a global substitution would
  # also rewrite the provenance mentions ("added by ai-infra") that must survive.
  function Test-Templated($rel){ @('CLAUDE.md','pyproject.toml','program.md') -ccontains ($rel -replace '\\','/') }

  # Get-Rendered — return the file's content with {{PROJECT_NAME}} resolved.
  # Reads/writes via the .NET API with an explicit BOM-less UTF-8 encoder,
  # rather than Get-Content/Set-Content: those cmdlets decode/re-encode using
  # the system ANSI codepage on Windows PowerShell 5.1, which corrupts the
  # non-ASCII characters these payload files contain on non-Latin locales.
  $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
  # Two tokens, not one: pyproject.toml's `name` field is PEP 508-validated and
  # rejects braces, so uv refuses to parse a tree holding {{PROJECT_NAME}} there.
  function Get-Rendered($path){
    [IO.File]::ReadAllText($path, $Utf8NoBom).
      Replace('{{PROJECT_NAME}}', $ProjectName).
      Replace('project-name-placeholder', $ProjectName)
  }

  # Copy-Payload — install one payload file, rendering it when templated.
  function Copy-Payload($s, $d, $rel) {
    if (Test-Templated $rel) { [IO.File]::WriteAllText($d, (Get-Rendered $s), $Utf8NoBom) }
    else { Copy-Item $s $d -Force }
  }

  Step "Installing $($files.Count) file(s) into $Target"
  foreach ($rel in $files) {
    $s = Join-Path $Src $rel; $d = Join-Path $Target $rel
    try {
      if (-not (Test-Path $d)) {
        New-Item -ItemType Directory -Force -Path (Split-Path $d -Parent) | Out-Null
        Copy-Payload $s $d $rel; $Installed += $rel; continue
      }
      switch ($Mode) {
        'override' { Copy-Item $d "$d.$ts.bak" -Force; Copy-Payload $s $d $rel; $Overwrote += $rel }
        'append'   {
          if (Is-Text $rel) {
            $sep = if ($rel -match '\.(gitignore|gitattributes)$') { "`n# --- added by ai-infra ---`n" } else { "`n<!-- added by ai-infra -->`n" }
            # Both read and write go through the .NET UTF-8 API here, not
            # Get-Content/Add-Content: Add-Content encodes with the system ANSI
            # codepage on Windows PowerShell 5.1, which silently mangles any
            # non-Latin character (e.g. U+2192) that ReadAllText correctly decoded.
            $body = if (Test-Templated $rel) { Get-Rendered $s } else { [IO.File]::ReadAllText($s, $Utf8NoBom) }
            [IO.File]::AppendAllText($d, ($sep + $body), $Utf8NoBom); $Appended += $rel
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

  # ---------- 5b. install the declared Claude plugins ----------
  # settings.json only DECLARES plugins: enabledPlugins toggles them on and
  # extraKnownMarketplaces names their sources. Neither key fetches code — Claude
  # Code loads a plugin only after it is installed under ~/.claude/plugins via the
  # `claude` CLI, so without this step the plugins report as "enabled in project
  # settings but isn't installed" and never load. We reconcile the declaration into
  # real installs: register each marketplace, then install every enabled plugin at
  # project scope (matching how settings.json enables them per-project). Uses
  # PowerShell's native JSON parser (no jq needed on Windows). Skipped with a
  # warning when the claude CLI is missing or $env:AI_INFRA_SKIP_PLUGINS=1.
  $PluginsOk = @(); $PluginsFail = @()
  $Settings = Join-Path $Target '.claude/settings.json'
  if ($env:AI_INFRA_SKIP_PLUGINS -eq '1') {
    Step "Skipping Claude plugin install (AI_INFRA_SKIP_PLUGINS=1)"
  } elseif (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Warn "claude CLI not found — plugins declared in settings.json were NOT installed. In the project run: claude plugin install <name>@<marketplace> --scope project"
  } elseif (-not (Test-Path $Settings)) {
    Warn "settings.json missing — skipped plugin install"
  } else {
    Step "Installing Claude plugins declared in settings.json"
    $cfg = Get-Content $Settings -Raw | ConvertFrom-Json
    # 1) register marketplaces (official explicitly + extras from settings), idempotent
    $repos = @('anthropics/claude-plugins-official')
    if ($cfg.extraKnownMarketplaces) {
      foreach ($m in $cfg.extraKnownMarketplaces.PSObject.Properties) {
        if ($m.Value.source.source -eq 'github' -and $m.Value.source.repo) { $repos += $m.Value.source.repo }
      }
    }
    foreach ($repo in $repos) { claude plugin marketplace add $repo 2>$null | Out-Null }
    # 2) install each enabled plugin at project scope, from within Target so the
    #    install attaches to this project (claude plugin uses the working dir).
    if ($cfg.enabledPlugins) {
      Push-Location $Target
      try {
        foreach ($p in $cfg.enabledPlugins.PSObject.Properties) {
          if ($p.Value -ne $true) { continue }
          claude plugin install $p.Name --scope project 2>$null | Out-Null
          if ($LASTEXITCODE -eq 0) { $PluginsOk += $p.Name } else { $PluginsFail += $p.Name }
        }
      } finally { Pop-Location }
    }
    $PluginsOk   | ForEach-Object { Ok $_ }
    $PluginsFail | ForEach-Object { Err "plugin failed: $_ (retry: claude plugin install $_ --scope project)" }
  }

  # ---------- 5c. install the plannotator binary the plugin calls ----------
  # The plannotator plugin only wires hooks that invoke a bare `plannotator` on PATH
  # (ExitPlanMode / EnterPlanMode); it does NOT ship the executable. When that plugin
  # is enabled we fetch the pinned, SIGNED release .exe from GitHub Releases and
  # verify its SHA256 sidecar before installing to %USERPROFILE%\.local\bin (no
  # install on mismatch). This avoids the upstream `irm … | iex` installer. Pin with
  # $env:PLANNOTATOR_VERSION; shares the $env:AI_INFRA_SKIP_PLUGINS gate.
  $PlannotatorVersion = if ($env:PLANNOTATOR_VERSION) { $env:PLANNOTATOR_VERSION } else { 'v0.22.0' }
  $planEnabled = $false
  if ((Test-Path $Settings) -and $env:AI_INFRA_SKIP_PLUGINS -ne '1') {
    try { $planEnabled = [bool]((Get-Content $Settings -Raw | ConvertFrom-Json).enabledPlugins.'plannotator@plannotator') } catch { $planEnabled = $false }
  }
  if ($planEnabled) {
    Step "Installing plannotator binary ($PlannotatorVersion, SHA256-verified)"
    $arch = switch ($env:PROCESSOR_ARCHITECTURE) { 'AMD64' { 'x64' } 'ARM64' { 'arm64' } default { $null } }
    if (-not $arch) {
      Warn "plannotator binary: unsupported arch $env:PROCESSOR_ARCHITECTURE — install manually from github.com/backnotprop/plannotator/releases"
    } else {
      $asset = "plannotator-win32-$arch.exe"
      $base  = "https://github.com/backnotprop/plannotator/releases/download/$PlannotatorVersion"
      $dest  = Join-Path $env:USERPROFILE '.local\bin'
      New-Item -ItemType Directory -Force -Path $dest | Out-Null
      $tmpf = Join-Path ([IO.Path]::GetTempPath()) ([Guid]::NewGuid().ToString('N') + '.exe')
      $tmps = "$tmpf.sha256"
      try {
        Invoke-WebRequest -UseBasicParsing -Uri "$base/$asset"        -OutFile $tmpf
        Invoke-WebRequest -UseBasicParsing -Uri "$base/$asset.sha256" -OutFile $tmps
        $want = ((Get-Content $tmps -Raw).Trim() -split '\s+')[0]
        $got  = (Get-FileHash -Algorithm SHA256 $tmpf).Hash
        if ($want -and ($want.ToLower() -eq $got.ToLower())) {
          if (Get-Command gh -ErrorAction SilentlyContinue) { try { gh attestation verify $tmpf --repo backnotprop/plannotator 2>$null | Out-Null } catch {} }
          Move-Item -Force $tmpf (Join-Path $dest 'plannotator.exe')
          $ToolsOk += "plannotator $PlannotatorVersion -> $dest\plannotator.exe"
          if (($env:Path -split ';') -notcontains $dest) { Warn "$dest is not on PATH — add it so the plannotator plugin hooks resolve the binary" }
        } else {
          $ToolsFail += "plannotator binary — SHA256 mismatch, NOT installed"
        }
      } catch {
        $ToolsFail += "plannotator binary ($PlannotatorVersion) — download/install failed"
      } finally {
        Remove-Item $tmps -ErrorAction SilentlyContinue
        if (Test-Path $tmpf) { Remove-Item $tmpf -ErrorAction SilentlyContinue }
      }
    }
  }

  # ---------- 6. external tools ----------
  if ($env:AI_INFRA_SKIP_TOOLS -eq '1') {
    Step "Skipping external tools (AI_INFRA_SKIP_TOOLS=1)"
  } else {
    Step "Installing external tools (graphify, codegraph, rtk)"
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
    # codegraph: symbol-level code index (third KB layer — see docs/pkb-schema.md).
    # npm-only and exact-pinned on purpose: the published manifest declares no install
    # scripts, unlike the advertised `irm … | iex` path. Telemetry ships ON by default,
    # so disable it as part of the install rather than trusting a follow-up step.
    $CodegraphVersion = if ($env:CODEGRAPH_VERSION) { $env:CODEGRAPH_VERSION } else { '1.4.1' }
    if (Get-Command npm -ErrorAction SilentlyContinue) {
      npm i -g "@colbymchenry/codegraph@$CodegraphVersion" --silent --no-fund --no-audit 2>$null | Out-Null
      if ($LASTEXITCODE -eq 0) {
        $ToolsOk += "codegraph v$CodegraphVersion (npm, pinned)"
        # Guard the call: npm's global bin dir is written to the machine PATH, but this
        # already-running process may not have it in $env:Path yet. Without the guard an
        # unresolvable command is a TERMINATING error under $ErrorActionPreference='Stop',
        # which would abort the whole installer (there is no catch) — so rtk would never
        # install and the summary would never print. Record the failure instead.
        if (Get-Command codegraph -ErrorAction SilentlyContinue) {
          codegraph telemetry off 2>$null | Out-Null
          if ($LASTEXITCODE -eq 0) { $ToolsOk += "codegraph telemetry off" }
          else { $ToolsFail += "codegraph telemetry STILL ON — run 'codegraph telemetry off'" }
        } else {
          $ToolsFail += "codegraph telemetry STILL ON — codegraph not on PATH yet; reopen the shell and run 'codegraph telemetry off'"
        }
      } else { $ToolsFail += "codegraph (npm)" }
    } else { $ToolsFail += "codegraph — npm not found" }
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
  if ($PluginsOk.Count -gt 0)   { Write-Host "  plugins installed:" -ForegroundColor White; $PluginsOk | ForEach-Object { Write-Host "      $_" } }
  if ($PluginsFail.Count -gt 0) { Write-Host "  plugins failed:" -ForegroundColor Red; $PluginsFail | ForEach-Object { Write-Host "      $_" } }
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
