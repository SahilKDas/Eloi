param(
  [switch] $SkipDefenderScan,
  [switch] $PreserveExisting,
  [string] $PythonExecutable = 'python',
  [string] $CaissaNetwork,
  [string] $CaissaLicenseGate,
  [string[]] $CaissaLicenseScope = @('binary', 'zip')
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
$caissaNetwork = Join-Path $projectRoot '.deps\caissa\eval-82-383B.pnn'
if ($CaissaNetwork) { $caissaNetwork = $CaissaNetwork }
$caissaLicenseGate = if ($CaissaLicenseGate) { $CaissaLicenseGate } else { Join-Path $projectRoot 'third_party\caissa\caissa-license-gate-template.v1.json' }
$caissaScopeArgs = @()
foreach ($scope in $CaissaLicenseScope | Where-Object { $_ }) {
  $clean = $scope.Trim()
  if ($clean) {
    $caissaScopeArgs += '--require-scope'
    $caissaScopeArgs += $clean
  }
}
if (-not $caissaScopeArgs) {
  $caissaScopeArgs = @('--require-scope', 'binary', '--require-scope', 'zip')
}
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

& $PythonExecutable -B (Join-Path $PSScriptRoot 'caissa_license_gate.py') --network $caissaNetwork --gate $caissaLicenseGate --sha256 '22249DE582912F46F73F7CF7410D6D72ECCC77696B0B857E99B97A45F3F37116' --bytes 50367040 @caissaScopeArgs
if ($LASTEXITCODE -ne 0) { throw 'Caissa license gate blocked packaging: network permission evidence missing or invalid.' }

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


