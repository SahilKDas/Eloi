param(
  [Parameter(Mandatory=$true)][string]$Worker,
  [ValidatePattern('^[a-z0-9-]+$')][string]$RunId = 'v400-r1',
  [string]$Output = '',
  [int64]$Epoch = 0
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$versionMatch = Select-String -LiteralPath (Join-Path $root 'Cargo.toml') -Pattern '^version = "([^"]+)"$' | Select-Object -First 1
if (-not $versionMatch) { throw 'Workspace version is missing' }
$version = $versionMatch.Matches[0].Groups[1].Value
$env:CARGO_BUILD_JOBS = '2'
$trackedDirty = & git -C $root status --porcelain --untracked-files=no
if ($LASTEXITCODE -ne 0 -or $trackedDirty) {
  throw 'Package source must have no tracked changes'
}
$sourceCommit = (& git -C $root rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $sourceCommit -notmatch '^[0-9a-f]{40}$') {
  throw 'Could not freeze the package source commit'
}
if ($Epoch -eq 0) { $Epoch = [int64]((& git -C $root show -s '--format=%ct' $sourceCommit).Trim()) }
$workerPath = (Resolve-Path $Worker).Path
$expectedWorkerHash = '043C0925DF8C608D0D87B9E6B1C761240DDD1901EE8CBA49E346686B28816B97'
if ((Get-FileHash -LiteralPath $workerPath -Algorithm SHA256).Hash -ne $expectedWorkerHash) {
  throw 'Caissa 2.0 donor hash mismatch'
}
if (-not $Output) { $Output = "dist\rust-rewrite-validation-$RunId" }
$outputRoot = Join-Path $root $Output
$scratch = Join-Path $root "tmp\rust-package-validation-$RunId"
$extractRoot = Join-Path $root "tmp\rust-package-extract-$RunId"
foreach ($path in @($outputRoot, $scratch, $extractRoot)) {
  if (Test-Path -LiteralPath $path) { throw "collision refused: $path" }
}
New-Item -ItemType Directory -Path $outputRoot, $scratch, $extractRoot | Out-Null
$temporaryUsage = (Get-ChildItem (Join-Path $root 'target'),(Join-Path $root 'tmp'),(Join-Path $root 'dist') -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
if ($temporaryUsage + 2500000000 -gt 10000000000 -or (Get-PSDrive C).Free -lt 3000000000) { throw 'Insufficient release storage quota/headroom' }
$metadataText = & cargo metadata --format-version 1 --locked --offline
if ($LASTEXITCODE -ne 0) { throw 'Could not resolve dependency licenses offline' }
$metadata = $metadataText | ConvertFrom-Json
$licenseLines = [Collections.Generic.List[string]]::new()
foreach ($dependency in $metadata.packages | Where-Object { $_.source } | Sort-Object name,version) {
  $licenseLines.Add("===== $($dependency.name) $($dependency.version) ($($dependency.license)) =====")
  $licenseRoot = Split-Path -Parent $dependency.manifest_path
  $notices = @(Get-ChildItem -LiteralPath $licenseRoot -File | Where-Object { $_.Name -match '^(LICENSE|LICENCE|COPYING|NOTICE)([.\-_]|$)' } | Sort-Object Name)
  if (-not $notices) { throw "Missing license text for $($dependency.name)" }
  foreach ($notice in $notices) { $licenseLines.Add($notice.Name); $licenseLines.Add([IO.File]::ReadAllText($notice.FullName)) }
}
$dependencyNotices = Join-Path $scratch 'RUST_DEPENDENCY_LICENSES.txt'
[IO.File]::WriteAllText($dependencyNotices,($licenseLines -join "`n"),[Text.UTF8Encoding]::new($false))

function Build-App([string]$Target, [bool]$Embed) {
  $targetPath = Join-Path $scratch $Target
  if ($Embed) { $env:ELOI_DONOR_WORKER = $workerPath }
  else { Remove-Item Env:ELOI_DONOR_WORKER -ErrorAction SilentlyContinue }
  $env:CARGO_TARGET_DIR = $targetPath
  $env:RUSTFLAGS = '-C target-feature=+crt-static -C link-arg=/Brepro'
  $usage = (Get-ChildItem (Join-Path $root 'target'),(Join-Path $root 'tmp'),(Join-Path $root 'dist') -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
  if ($usage + 500000000 -gt 10000000000) { throw 'Release scratch quota would be exceeded' }
  & cargo build --release -p eloi-rs --locked --offline
  if ($LASTEXITCODE -ne 0) { throw "Rust build failed: $Target" }
  $executable = Join-Path $targetPath 'release\eloi-rs.exe'
  $bytes = [IO.File]::ReadAllBytes($executable)
  if ($bytes[0] -ne 0x4d -or $bytes[1] -ne 0x5a) { throw "invalid PE image: $executable" }
  $pe = [BitConverter]::ToInt32($bytes, 0x3c)
  if ([Text.Encoding]::ASCII.GetString($bytes, $pe, 4) -ne "PE`0`0") {
    throw "invalid PE signature: $executable"
  }
  [Array]::Clear($bytes, $pe + 8, 4)
  [IO.File]::WriteAllBytes($executable, $bytes)
  return $executable
}

function Stage([string]$Name, [string]$Executable, [bool]$Split) {
  $folder = Join-Path $scratch $Name
  New-Item -ItemType Directory -Path $folder | Out-Null
  Copy-Item -LiteralPath $Executable -Destination (Join-Path $folder 'Eloi.exe')
  Copy-Item -LiteralPath (Join-Path $root 'config.example.yml') -Destination (Join-Path $folder 'config.yml')
  Copy-Item -LiteralPath (Join-Path $root 'README.md') -Destination $folder
  Copy-Item -LiteralPath (Join-Path $root 'LICENSE') -Destination $folder
  Copy-Item -LiteralPath (Join-Path $root 'THIRD_PARTY_NOTICES.md') -Destination $folder
  Copy-Item -LiteralPath (Join-Path $root 'third_party\caissa20\LICENSE') -Destination (Join-Path $folder 'CAISSA_LICENSE.txt')
  Copy-Item -LiteralPath (Join-Path $root 'assets\chess_maestro_bw\ATTRIBUTION.md') -Destination (Join-Path $folder 'CHESS_PIECES_ATTRIBUTION.md')
  Copy-Item -LiteralPath $dependencyNotices -Destination $folder
  Copy-Item -LiteralPath (Join-Path $root 'packaging\V4_QUICK_START.md') -Destination (Join-Path $folder 'QUICK_START.md')
  Copy-Item -LiteralPath (Join-Path $root 'RELEASE_V4_0_0.md') -Destination $folder
  [IO.File]::WriteAllText((Join-Path $folder 'Open-Teams.cmd'),"@echo off`r`ncd /d `"%~dp0`"`r`n`"%~dp0Eloi.exe`" --four-player-gui`r`n",[Text.UTF8Encoding]::new($false))
  [IO.File]::WriteAllText((Join-Path $folder 'Open-OperationsCenter.cmd'),"@echo off`r`ncd /d `"%~dp0`"`r`n`"%~dp0Eloi.exe`" --operations-center --config `"%~dp0config.yml`"`r`n",[Text.UTF8Encoding]::new($false))
  [IO.File]::WriteAllText(
    (Join-Path $folder 'SOURCE_COMMIT.txt'),
    "$sourceCommit`n",
    [Text.UTF8Encoding]::new($false))
  if ($Split) {
    Copy-Item -LiteralPath $workerPath -Destination (Join-Path $folder 'eloi-caissa-2.0.exe')
  }
  $manifest = foreach ($file in Get-ChildItem -LiteralPath $folder -File | Sort-Object Name) {
    '{0}  {1}' -f (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash, $file.Name
  }
  [IO.File]::WriteAllText(
    (Join-Path $folder 'SHA256SUMS.txt'),
    (($manifest -join "`n") + "`n"),
    [Text.UTF8Encoding]::new($false))
  $expected = @('config.yml','Eloi.exe','LICENSE','README.md','SHA256SUMS.txt',
    'SOURCE_COMMIT.txt','THIRD_PARTY_NOTICES.md','CAISSA_LICENSE.txt','CHESS_PIECES_ATTRIBUTION.md',
    'RUST_DEPENDENCY_LICENSES.txt','QUICK_START.md','RELEASE_V4_0_0.md','Open-Teams.cmd','Open-OperationsCenter.cmd')
  if ($Split) { $expected += @('eloi-caissa-2.0.exe') }
  $actual = @(Get-ChildItem -LiteralPath $folder -File | ForEach-Object Name | Sort-Object)
  $expected = @($expected | Sort-Object)
  if (Compare-Object $expected $actual) {
    throw "unexpected package contents: $Name"
  }
  return $folder
}

function SmokeExtract([string]$Zip, [bool]$Split) {
  $name = [IO.Path]::GetFileNameWithoutExtension($Zip)
  $destination = Join-Path $extractRoot $name
  Expand-Archive -LiteralPath $Zip -DestinationPath $destination
  $exe = Join-Path $destination 'Eloi.exe'
  $version = (& $exe --version).Trim()
  if ($LASTEXITCODE -ne 0 -or $version -ne "Eloi $script:version") {
    throw "version smoke failed: $name"
  }
  & $exe --check-config --config (Join-Path $destination 'config.yml') | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "config smoke failed: $name" }
  $python = Join-Path $root '.deps\lichess-bot\.venv\Scripts\python.exe'
  if (-not (Test-Path -LiteralPath $python)) {
    throw 'Pinned validation Python environment is unavailable'
  }
  & $python (Join-Path $root 'scripts\rust_uci_smoke.py') --engine $exe
  if ($LASTEXITCODE -ne 0) { throw "UCI lifecycle smoke failed: $name" }
  & $python (Join-Path $root 'scripts\four_player_teams_smoke.py') --engine $exe --output (Join-Path $destination 'teams-smoke.json')
  if ($LASTEXITCODE -ne 0) { throw "Teams lifecycle smoke failed: $name" }
  $configText = [IO.File]::ReadAllText((Join-Path $destination 'config.yml'))
  if ($configText -notmatch 'token:\s*""' -or $configText -notmatch 'enabled:\s*false') { throw 'Packaged config is not credential-empty and disabled' }
  $image=[IO.File]::ReadAllBytes($exe);$offset=[BitConverter]::ToInt32($image,0x3c)
  if ([BitConverter]::ToUInt32($image,$offset+8) -ne 0) { throw 'Eloi PE timestamp is not zero' }
  if ($Split) {
    $hash = (Get-FileHash -LiteralPath (Join-Path $destination 'eloi-caissa-2.0.exe') -Algorithm SHA256).Hash
    if ($hash -ne $expectedWorkerHash) { throw "extracted donor mismatch: $name" }
  }
}

try {
  $standaloneA = Build-App 'standalone-a' $true
  $standaloneB = Build-App 'standalone-b' $true
  $splitA = Build-App 'split-a' $false
  $splitB = Build-App 'split-b' $false
  $pairs = @(
    @{ A = $standaloneA; B = $standaloneB },
    @{ A = $splitA; B = $splitB }
  )
  foreach ($pair in $pairs) {
    if ((Get-FileHash $pair.A -Algorithm SHA256).Hash -ne
        (Get-FileHash $pair.B -Algorithm SHA256).Hash) {
      throw "independent executable builds differ: $($pair.A)"
    }
  }
  $standalone = Stage "Eloi-v$version-windows-x64-standalone" $standaloneA $false
  $split = Stage "Eloi-v$version-windows-x64-exoskeleton" $splitA $true
  foreach ($folder in @($standalone,$split)) {
    $name = Split-Path $folder -Leaf
    $zipA = Join-Path $outputRoot ($name + '.zip')
    $zipB = Join-Path $scratch ($name + '-repro.zip')
    & python -B (Join-Path $root 'scripts\deterministic_zip.py') $folder $zipA $Epoch
    if ($LASTEXITCODE -ne 0) { throw "archive A failed: $name" }
    & python -B (Join-Path $root 'scripts\deterministic_zip.py') $folder $zipB $Epoch
    if ($LASTEXITCODE -ne 0) { throw "archive B failed: $name" }
    if ((Get-FileHash $zipA -Algorithm SHA256).Hash -ne
        (Get-FileHash $zipB -Algorithm SHA256).Hash) {
      throw "deterministic archives differ: $name"
    }
    SmokeExtract $zipA ($name -like '*exoskeleton')
  }
  Get-ChildItem -LiteralPath $outputRoot -File | Get-FileHash -Algorithm SHA256
}
finally {
  Remove-Item Env:ELOI_DONOR_WORKER -ErrorAction SilentlyContinue
  Remove-Item Env:CARGO_TARGET_DIR -ErrorAction SilentlyContinue
  Remove-Item Env:RUSTFLAGS -ErrorAction SilentlyContinue
}
