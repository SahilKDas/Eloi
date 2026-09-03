param(
  [switch] $SkipDefenderScan,
  [switch] $PreserveExisting,
  [string] $PythonExecutable = 'python'
)

$ErrorActionPreference = 'Stop'

if ($PreserveExisting) {
  if ($SkipDefenderScan) { throw 'Preservation release workflow cannot waive security validation.' }
  & $PythonExecutable -B (Join-Path $PSScriptRoot 'release_v250.py') build
  if ($LASTEXITCODE -ne 0) { throw 'Preservation release validation failed.' }
  Write-Host 'Preserved packages built. Complete recorded Defender/GUI/publication checks before publishing.'
  return
}

$projectRoot = Split-Path -Parent $PSScriptRoot
$cmakeSource = Get-Content -LiteralPath (Join-Path $projectRoot 'CMakeLists.txt') -Raw
if ($cmakeSource -notmatch 'project\(Eloi VERSION ([0-9]+\.[0-9]+\.[0-9]+)') {
  throw 'Could not determine Eloi version from CMakeLists.txt'
}
$releaseVersion = $Matches[1]
if ($cmakeSource -match 'set\(ELOI_PRERELEASE "([^"]*)"\)' -and $Matches[1]) {
  $releaseVersion += '-' + $Matches[1]
}

if (& git -C $projectRoot status --porcelain) {
  throw 'Commit the exact source first; release packaging requires a clean worktree.'
}

$artifactRoot = Join-Path $projectRoot 'dist\artifacts'
$resolvedRoot = [IO.Path]::GetFullPath($projectRoot).TrimEnd('\')
$resolvedArtifacts = [IO.Path]::GetFullPath($artifactRoot)
if (-not $resolvedArtifacts.StartsWith(
    $resolvedRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
  throw "Artifact path escapes the repository: $resolvedArtifacts"
}
if (Test-Path -LiteralPath $resolvedArtifacts) {
  Remove-Item -LiteralPath $resolvedArtifacts -Recurse -Force
}
New-Item -ItemType Directory -Path $resolvedArtifacts | Out-Null

& (Join-Path $PSScriptRoot 'verify-reproducible.ps1') -StageRelease
if ($LASTEXITCODE -ne 0) { throw 'Canonical two-build proof failed' }

$releaseRoot = Join-Path $projectRoot 'dist\release'
$releaseFiles = @(Get-ChildItem -LiteralPath $releaseRoot -File)
if ($releaseFiles.Count -ne 2 -or
    @($releaseFiles.Name | Sort-Object) -join ',' -ne 'config.yml,Eloi.exe') {
  throw 'Canonical staging must contain exactly Eloi.exe and config.yml'
}

$standaloneName = "Eloi-v$releaseVersion-windows-x64-standalone.zip"
$standaloneZip = Join-Path $resolvedArtifacts $standaloneName
Compress-Archive -LiteralPath @(
  (Join-Path $releaseRoot 'Eloi.exe'),
  (Join-Path $releaseRoot 'config.yml')
) -DestinationPath $standaloneZip -CompressionLevel Optimal
$standaloneEntries = @(tar -tf $standaloneZip)
if ($LASTEXITCODE -ne 0 -or $standaloneEntries.Count -ne 2 -or
    @($standaloneEntries | Sort-Object) -join ',' -ne 'config.yml,Eloi.exe') {
  throw 'Standalone ZIP must contain exactly Eloi.exe and config.yml at its root'
}

if (-not $SkipDefenderScan) {
  $scanner = 'C:\Program Files\Windows Defender\MpCmdRun.exe'
  foreach ($path in @((Join-Path $releaseRoot 'Eloi.exe'), $standaloneZip)) {
    & $scanner -Scan -ScanType 3 -File $path -DisableRemediation
    if ($LASTEXITCODE -ne 0) { throw "Defender scan failed for $path" }
  }
}

$splitArguments = @{ OutputRoot = $resolvedArtifacts }
if ($SkipDefenderScan) { $splitArguments.SkipDefenderScan = $true }
& (Join-Path $PSScriptRoot 'build-windows-exoskeleton-zip.ps1') @splitArguments
if ($LASTEXITCODE -ne 0) { throw 'Exoskeleton package build failed' }

$splitZip = Join-Path $resolvedArtifacts `
  "Eloi-v$releaseVersion-windows-x64-exoskeleton.zip"
if (-not (Test-Path -LiteralPath $splitZip -PathType Leaf)) {
  throw "Exoskeleton ZIP was not created: $splitZip"
}
$artifactEntries = @(Get-ChildItem -LiteralPath $resolvedArtifacts -Force)
$expectedArtifacts = @($standaloneName, (Split-Path -Leaf $splitZip)) | Sort-Object
if ($artifactEntries.Count -ne 2 -or
    @($artifactEntries.Name | Sort-Object) -join ',' -ne
      ($expectedArtifacts -join ',') -or
    @($artifactEntries | Where-Object { -not $_.PSIsContainer }).Count -ne 2) {
  throw 'Release artifacts must contain exactly the standalone and Exoskeleton ZIPs'
}

Write-Host 'Golden release artifacts:'
foreach ($path in @($standaloneZip, $splitZip)) {
  $item = Get-Item -LiteralPath $path
  $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
  Write-Host "  $($item.Name)  $($item.Length) bytes  SHA-256 $hash"
}
