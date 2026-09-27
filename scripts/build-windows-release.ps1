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
if ($releaseFiles.Count -ne 4 -or
    @($releaseFiles.Name | Sort-Object) -join ',' -ne 'CAISSA_LICENSE.txt,config.yml,Eloi.exe,eval-71-v1.25.pnn') {
  throw 'Canonical staging must contain exactly the v3 executable, config, Caissa network, and license'
}

$standaloneName = "Eloi-v$releaseVersion-windows-x64-standalone.zip"
$standaloneZip = Join-Path $resolvedArtifacts $standaloneName
$standaloneProof = Join-Path $resolvedArtifacts ($standaloneName + '.proof')
$epoch = (Get-Content -LiteralPath (Join-Path $projectRoot 'reproducibility.lock.json') -Raw |
  ConvertFrom-Json).source_date_epoch
& $PythonExecutable -B (Join-Path $PSScriptRoot 'deterministic_zip.py') `
  $releaseRoot $standaloneZip ([string]$epoch)
if ($LASTEXITCODE -ne 0) { throw 'Standalone deterministic archive A failed' }
& $PythonExecutable -B (Join-Path $PSScriptRoot 'deterministic_zip.py') `
  $releaseRoot $standaloneProof ([string]$epoch)
if ($LASTEXITCODE -ne 0) { throw 'Standalone deterministic archive B failed' }
if ((Get-FileHash -LiteralPath $standaloneZip -Algorithm SHA256).Hash -ne
    (Get-FileHash -LiteralPath $standaloneProof -Algorithm SHA256).Hash) {
  throw 'Standalone deterministic archive constructions differ'
}
Remove-Item -LiteralPath $standaloneProof -Force
$standaloneEntries = @(tar -tf $standaloneZip)
if ($LASTEXITCODE -ne 0 -or $standaloneEntries.Count -ne 4 -or
    @($standaloneEntries | Sort-Object) -join ',' -ne 'CAISSA_LICENSE.txt,config.yml,Eloi.exe,eval-71-v1.25.pnn') {
  throw 'Standalone ZIP must contain exactly the v3 executable, config, Caissa network, and license at its root'
}

if (-not $SkipDefenderScan) {
  $scanner = 'C:\Program Files\Windows Defender\MpCmdRun.exe'
  foreach ($path in @((Join-Path $releaseRoot 'Eloi.exe'), $standaloneZip)) {
    & $scanner -Scan -ScanType 3 -File $path -DisableRemediation
    if ($LASTEXITCODE -ne 0) { throw "Defender scan failed for $path" }
  }
}

$splitBuildA = Join-Path $projectRoot "tmp\release-v$releaseVersion-exoskeleton-A-build"
$splitBuildB = Join-Path $projectRoot "tmp\release-v$releaseVersion-exoskeleton-B-build"
$splitOutputB = Join-Path $projectRoot "tmp\release-v$releaseVersion-exoskeleton-B-output"
$splitArguments = @{ OutputRoot = $resolvedArtifacts; BuildRoot = $splitBuildA }
if ($SkipDefenderScan) { $splitArguments.SkipDefenderScan = $true }
& (Join-Path $PSScriptRoot 'build-windows-exoskeleton-zip.ps1') @splitArguments
if ($LASTEXITCODE -ne 0) { throw 'Exoskeleton package build failed' }

$splitZip = Join-Path $resolvedArtifacts `
  "Eloi-v$releaseVersion-windows-x64-exoskeleton.zip"
if (-not (Test-Path -LiteralPath $splitZip -PathType Leaf)) {
  throw "Exoskeleton ZIP was not created: $splitZip"
}
$splitProofArguments = @{ OutputRoot = $splitOutputB; BuildRoot = $splitBuildB }
if ($SkipDefenderScan) { $splitProofArguments.SkipDefenderScan = $true }
& (Join-Path $PSScriptRoot 'build-windows-exoskeleton-zip.ps1') @splitProofArguments
if ($LASTEXITCODE -ne 0) { throw 'Independent Exoskeleton package build failed' }
$splitProofZip = Join-Path $splitOutputB `
  "Eloi-v$releaseVersion-windows-x64-exoskeleton.zip"
if ((Get-FileHash -LiteralPath $splitZip -Algorithm SHA256).Hash -ne
    (Get-FileHash -LiteralPath $splitProofZip -Algorithm SHA256).Hash) {
  throw 'Independent Exoskeleton ZIP constructions differ'
}

# Both builders retain extracted staging for inspection. After byte equality is
# proven, remove only these known generated directories so dist/artifacts holds
# exactly the two golden archives promised by the release contract.
$splitPackageA = Join-Path $resolvedArtifacts `
  "Eloi-v$releaseVersion-windows-x64-exoskeleton"
foreach ($generated in @($splitPackageA, $splitBuildA, $splitOutputB, $splitBuildB)) {
  $resolvedGenerated = [IO.Path]::GetFullPath($generated)
  if (-not $resolvedGenerated.StartsWith(
      $resolvedRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove generated path outside repository: $resolvedGenerated"
  }
  if (Test-Path -LiteralPath $resolvedGenerated) {
    Remove-Item -LiteralPath $resolvedGenerated -Recurse -Force
  }
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
