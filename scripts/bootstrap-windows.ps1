$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$depsRoot = Join-Path $projectRoot '.deps'
$packageCache = Join-Path $depsRoot 'packages'
$skiaRoot = Join-Path $depsRoot 'skia108'
$lock = Get-Content -LiteralPath (Join-Path $projectRoot 'reproducibility.lock.json') -Raw |
  ConvertFrom-Json
$env:SOURCE_DATE_EPOCH = [string]$lock.source_date_epoch

New-Item -ItemType Directory -Force -Path $packageCache, $skiaRoot | Out-Null

$tar = 'C:\msys64\usr\bin\tar.exe'
if (-not (Test-Path $tar)) {
  $tarCommand = Get-Command tar.exe -ErrorAction Stop
  $tar = $tarCommand.Source
}

function Install-Archive {
  param(
    [Parameter(Mandatory)] $Dependency,
    [Parameter(Mandatory)] [string] $Destination
  )
  $archive = Join-Path $packageCache $Dependency.archive
  if (-not (Test-Path $archive)) {
    Write-Host "Downloading $($Dependency.name) $($Dependency.version)"
    Invoke-WebRequest -UseBasicParsing -Uri $Dependency.url -OutFile $archive
  }
  $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
  if ($actual -ne $Dependency.sha256) {
    throw "Hash mismatch for $($Dependency.archive). Expected $($Dependency.sha256), got $actual"
  }
  & $tar --force-local --zstd -xf $archive -C $Destination
  if ($LASTEXITCODE -ne 0) { throw "Could not extract $($Dependency.archive)" }
}

$skia = $lock.downloaded_dependencies | Where-Object name -eq 'Skia'
Install-Archive $skia $skiaRoot

& (Join-Path $PSScriptRoot 'bootstrap-static-codecs.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Could not build static codecs' }

& (Join-Path $PSScriptRoot 'verify-toolchain.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Pinned dependency verification failed' }

Write-Host 'Eloi dependencies are hash-verified and ready in .deps (ignored by git).'
