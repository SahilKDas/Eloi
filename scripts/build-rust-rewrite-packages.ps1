param(
  [Parameter(Mandatory=$true)][string]$Worker,
  [string]$Output = 'dist\rust-rewrite-validation-r5',
  [int64]$Epoch = 1780000000
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$trackedDirty = & git -C $root status --porcelain --untracked-files=no
if ($LASTEXITCODE -ne 0 -or $trackedDirty) {
  throw 'Package source must have no tracked changes'
}
$sourceCommit = (& git -C $root rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $sourceCommit -notmatch '^[0-9a-f]{40}$') {
  throw 'Could not freeze the package source commit'
}
$workerPath = (Resolve-Path $Worker).Path
$expectedWorkerHash = '043C0925DF8C608D0D87B9E6B1C761240DDD1901EE8CBA49E346686B28816B97'
if ((Get-FileHash -LiteralPath $workerPath -Algorithm SHA256).Hash -ne $expectedWorkerHash) {
  throw 'Caissa 2.0 donor hash mismatch'
}
$outputRoot = Join-Path $root $Output
$scratch = Join-Path $root 'tmp\rust-package-validation-r5'
$extractRoot = Join-Path $root 'tmp\rust-package-extract-r5'
foreach ($path in @($outputRoot, $scratch, $extractRoot)) {
  if (Test-Path -LiteralPath $path) { throw "collision refused: $path" }
}
New-Item -ItemType Directory -Path $outputRoot, $scratch, $extractRoot | Out-Null

function Build-App([string]$Target, [bool]$Embed) {
  $targetPath = Join-Path $scratch $Target
  if ($Embed) { $env:ELOI_DONOR_WORKER = $workerPath }
  else { Remove-Item Env:ELOI_DONOR_WORKER -ErrorAction SilentlyContinue }
  $env:CARGO_TARGET_DIR = $targetPath
  $env:RUSTFLAGS = '-C link-arg=/Brepro'
  & cargo build --release -p eloi-rs --locked
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
  [IO.File]::WriteAllText(
    (Join-Path $folder 'SOURCE_COMMIT.txt'),
    "$sourceCommit`n",
    [Text.UTF8Encoding]::new($false))
  if ($Split) {
    Copy-Item -LiteralPath $workerPath -Destination (Join-Path $folder 'eloi-caissa-2.0.exe')
    Copy-Item -LiteralPath (Join-Path $root 'third_party\caissa20\LICENSE') `
      -Destination (Join-Path $folder 'CAISSA_LICENSE.txt')
  }
  $manifest = foreach ($file in Get-ChildItem -LiteralPath $folder -File | Sort-Object Name) {
    '{0}  {1}' -f (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash, $file.Name
  }
  [IO.File]::WriteAllText(
    (Join-Path $folder 'SHA256SUMS.txt'),
    (($manifest -join "`n") + "`n"),
    [Text.UTF8Encoding]::new($false))
  $expected = @('config.yml','Eloi.exe','LICENSE','README.md','SHA256SUMS.txt',
    'SOURCE_COMMIT.txt','THIRD_PARTY_NOTICES.md')
  if ($Split) { $expected += @('CAISSA_LICENSE.txt','eloi-caissa-2.0.exe') }
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
  if ($LASTEXITCODE -ne 0 -or $version -ne 'Eloi 3.9.0') {
    throw "version smoke failed: $name"
  }
  & $exe --check-config --config (Join-Path $destination 'config.yml') | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "config smoke failed: $name" }
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
  $standalone = Stage 'Eloi-v3.9.0-windows-x64-standalone' $standaloneA $false
  $split = Stage 'Eloi-v3.9.0-windows-x64-exoskeleton' $splitA $true
  foreach ($folder in @($standalone,$split)) {
    $name = Split-Path $folder -Leaf
    $zipA = Join-Path $outputRoot ($name + '-A.zip')
    $zipB = Join-Path $outputRoot ($name + '-B.zip')
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
