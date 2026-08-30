param(
  [switch] $RequirePackageArchives,
  [switch] $SkipLinkedLibraries
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$lockPath = Join-Path $projectRoot 'reproducibility.lock.json'
$lock = Get-Content -LiteralPath $lockPath -Raw | ConvertFrom-Json
$pacman = 'C:\msys64\usr\bin\pacman.exe'
$packageCache = 'C:\msys64\var\cache\pacman\pkg'

function Assert-Sha256 {
  param(
    [Parameter(Mandatory)] [string] $Path,
    [Parameter(Mandatory)] [string] $Expected,
    [Parameter(Mandatory)] [string] $Description
  )
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    throw "$Description is missing: $Path"
  }
  $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
  if ($actual -ne $Expected) {
    throw "$Description hash mismatch. Expected $Expected, got $actual ($Path)"
  }
  Write-Host "verified $Description"
}

if (-not (Test-Path -LiteralPath $pacman -PathType Leaf)) {
  throw "MSYS2 pacman was not found at $pacman"
}

foreach ($package in $lock.toolchain_packages) {
  $installed = (& $pacman -Q $package.name 2>$null)
  if ($LASTEXITCODE -ne 0) {
    throw "Required MSYS2 package is not installed: $($package.name)"
  }
  $expected = "$($package.name) $($package.version)"
  if ($installed.Trim() -ne $expected) {
    throw "Toolchain package mismatch. Expected '$expected', got '$($installed.Trim())'"
  }
  Write-Host "verified $expected"

  $archivePath = Join-Path $packageCache $package.archive
  if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
    $length = (Get-Item -LiteralPath $archivePath).Length
    if ($length -ne [int64]$package.size) {
      throw "Package archive size mismatch for $($package.archive)"
    }
    Assert-Sha256 $archivePath $package.sha256 "package archive $($package.archive)"
  } elseif ($RequirePackageArchives) {
    throw "Pinned package archive is absent from $packageCache`: $($package.archive)"
  } else {
    Write-Warning "Package archive not cached; installed version and executable hashes are still checked: $($package.archive)"
  }
}

foreach ($tool in $lock.tool_executables) {
  Assert-Sha256 $tool.path $tool.sha256 "tool $($tool.path)"
}

foreach ($dependency in $lock.downloaded_dependencies) {
  $archivePath = Join-Path $projectRoot ('.deps\packages\' + $dependency.archive)
  if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
    if ($null -ne $dependency.size -and
        (Get-Item -LiteralPath $archivePath).Length -ne [int64]$dependency.size) {
      throw "Dependency archive size mismatch for $($dependency.archive)"
    }
    Assert-Sha256 $archivePath $dependency.sha256 "dependency archive $($dependency.archive)"
  } elseif ($RequirePackageArchives) {
    throw "Pinned dependency archive is missing: $archivePath"
  } else {
    Write-Warning "Dependency archive not cached; linked output is still checked: $($dependency.archive)"
  }
}

if (-not $SkipLinkedLibraries) {
  foreach ($library in $lock.linked_static_libraries) {
    $libraryPath = Join-Path $projectRoot $library.path
    Assert-Sha256 $libraryPath $library.sha256 "linked library $($library.path)"
  }
}

Write-Host 'The Eloi toolchain and build inputs match reproducibility.lock.json.'
