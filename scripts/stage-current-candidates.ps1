param(
  [switch] $SkipBuild
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$distRoot = Join-Path $projectRoot 'dist'
$currentRoot = Join-Path $distRoot 'current'
$buildRoot = Join-Path $projectRoot 'build-release'
$cmakeSource = Get-Content -LiteralPath (Join-Path $projectRoot 'CMakeLists.txt') -Raw
if ($cmakeSource -notmatch 'project\(Eloi VERSION ([0-9]+\.[0-9]+\.[0-9]+)') {
  throw 'Could not determine Eloi version from CMakeLists.txt'
}
$version = $Matches[1]
$prerelease = ''
if ($cmakeSource -match 'set\(ELOI_PRERELEASE "([^"]*)"\)' -and $Matches[1]) {
  $prerelease = '-' + $Matches[1]
}
$candidate = "Eloi-v$version$prerelease-windows-x64"

function Assert-UnderDist {
  param([string] $Path)
  $root = [IO.Path]::GetFullPath($distRoot).TrimEnd('\')
  $resolved = [IO.Path]::GetFullPath($Path)
  if (-not $resolved.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "Path escapes dist: $resolved"
  }
  return $resolved
}

function Invoke-Checked {
  param([string] $FilePath, [string[]] $Arguments)
  & $FilePath @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "$FilePath failed with exit code $LASTEXITCODE"
  }
}

$null = Assert-UnderDist $currentRoot
if (Test-Path -LiteralPath $currentRoot) {
  Remove-Item -LiteralPath $currentRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $currentRoot | Out-Null

if (-not $SkipBuild) {
  Invoke-Checked 'cmake' @(
    '--build', $buildRoot, '--config', 'Release', '--parallel', '3'
  )
  Invoke-Checked 'ctest' @(
    '--test-dir', $buildRoot, '-C', 'Release', '--output-on-failure'
  )
}

$standaloneName = $candidate + '-standalone'
$standaloneRoot = Join-Path $currentRoot $standaloneName
$standaloneZip = Join-Path $currentRoot ($standaloneName + '.zip')
New-Item -ItemType Directory -Force -Path $standaloneRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $buildRoot 'Eloi.exe') -Destination $standaloneRoot
Copy-Item -LiteralPath (Join-Path $projectRoot 'config.example.yml') `
  -Destination (Join-Path $standaloneRoot 'config.yml')
Compress-Archive -Path (Join-Path $standaloneRoot '*') `
  -DestinationPath $standaloneZip -CompressionLevel Optimal
$entries = @(tar -tf $standaloneZip)
if ($LASTEXITCODE -ne 0 -or $entries.Count -ne 2 -or
    @($entries | Sort-Object) -join ',' -ne 'config.yml,Eloi.exe') {
  throw 'Rolling standalone candidate must contain exactly Eloi.exe and config.yml.'
}
Remove-Item -LiteralPath $standaloneRoot -Recurse -Force

& (Join-Path $PSScriptRoot 'build-windows-exoskeleton-zip.ps1') `
  -AllowDirty -SkipDefenderScan -OutputRoot $currentRoot
if ($LASTEXITCODE -ne 0) { throw 'Exoskeleton candidate staging failed.' }

$archives = @(Get-ChildItem -LiteralPath $currentRoot -File -Filter '*.zip')
if ($archives.Count -ne 2) {
  throw 'Rolling candidate staging must produce exactly two ZIP archives.'
}
$extracted = @(Get-ChildItem -LiteralPath $currentRoot -Directory)
foreach ($directory in $extracted) {
  $resolved = Assert-UnderDist $directory.FullName
  Remove-Item -LiteralPath $resolved -Recurse -Force
}
$remaining = @(Get-ChildItem -LiteralPath $currentRoot -Force)
if ($remaining.Count -ne 2 -or @($remaining | Where-Object Extension -ne '.zip')) {
  throw 'Rolling candidate area must contain only the two ZIP archives.'
}
Write-Host 'Current rolling release candidates:'
foreach ($archive in $archives | Sort-Object Name) {
  $hash = (Get-FileHash -LiteralPath $archive.FullName -Algorithm SHA256).Hash
  Write-Host "$($archive.FullName)  SHA-256 $hash"
}
