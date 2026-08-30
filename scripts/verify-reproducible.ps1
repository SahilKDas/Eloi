param(
  [switch] $Keep,
  [switch] $StageRelease
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$lock = Get-Content -LiteralPath (Join-Path $projectRoot 'reproducibility.lock.json') -Raw |
  ConvertFrom-Json
$cmake = 'C:/msys64/ucrt64/bin/cmake.exe'
$ctest = 'C:/msys64/ucrt64/bin/ctest.exe'
$ninja = 'C:/msys64/ucrt64/bin/ninja.exe'
$cxx = 'C:/msys64/ucrt64/bin/c++.exe'
$windres = 'C:/msys64/ucrt64/bin/windres.exe'
$skiaRoot = Join-Path $projectRoot '.deps\skia108\ucrt64'
$staticRoot = Join-Path $projectRoot '.deps\static-runtime'
$tempParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\')
$tempRoot = Join-Path $tempParent ("Eloi-repro-" + [guid]::NewGuid().ToString('N'))
$archive = Join-Path $tempRoot 'source.zip'

function Invoke-Checked {
  param(
    [Parameter(Mandatory)] [string] $FilePath,
    [Parameter(Mandatory)] [string[]] $Arguments
  )
  & $FilePath @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "$FilePath failed with exit code $LASTEXITCODE"
  }
}

function Test-FilesEqual {
  param([string] $Left, [string] $Right)
  $leftInfo = Get-Item -LiteralPath $Left
  $rightInfo = Get-Item -LiteralPath $Right
  if ($leftInfo.Length -ne $rightInfo.Length) { return $false }
  $leftStream = [System.IO.File]::OpenRead($Left)
  $rightStream = [System.IO.File]::OpenRead($Right)
  try {
    $leftBuffer = [byte[]]::new(1048576)
    $rightBuffer = [byte[]]::new(1048576)
    while (($count = $leftStream.Read($leftBuffer, 0, $leftBuffer.Length)) -gt 0) {
      if ($rightStream.Read($rightBuffer, 0, $rightBuffer.Length) -ne $count) {
        return $false
      }
      for ($i = 0; $i -lt $count; ++$i) {
        if ($leftBuffer[$i] -ne $rightBuffer[$i]) { return $false }
      }
    }
    return $true
  } finally {
    $leftStream.Dispose()
    $rightStream.Dispose()
  }
}

function Assert-PeTimestampZero {
  param([string] $Path)
  $stream = [System.IO.File]::OpenRead($Path)
  $reader = [System.IO.BinaryReader]::new($stream)
  try {
    $stream.Position = 0x3c
    $peOffset = $reader.ReadInt32()
    $stream.Position = $peOffset
    if ($reader.ReadUInt32() -ne 0x00004550) { throw "$Path is not a PE image" }
    $stream.Position = $peOffset + 8
    $timestamp = $reader.ReadUInt32()
    if ($timestamp -ne 0) { throw "$Path has a nonzero PE timestamp: $timestamp" }
  } finally {
    $reader.Dispose()
    $stream.Dispose()
  }
}

function Assert-TwoFileRelease {
  param([string] $Directory)
  $files = @(Get-ChildItem -LiteralPath $Directory -File)
  $directories = @(Get-ChildItem -LiteralPath $Directory -Directory)
  if ($directories.Count -ne 0 -or $files.Count -ne 2) {
    throw "Release contract failed in $Directory; expected exactly two files"
  }
  $names = @($files.Name | Sort-Object)
  if ($names[0] -ne 'config.yml' -or $names[1] -ne 'Eloi.exe') {
    throw "Release contract failed in $Directory; found: $($names -join ', ')"
  }
}

function Build-Copy {
  param([string] $Name)
  $source = Join-Path $tempRoot "$Name\source"
  $build = Join-Path $tempRoot "$Name\build"
  Expand-Archive -LiteralPath $archive -DestinationPath $source

  Invoke-Checked $cmake @(
    '-S', $source,
    '-B', $build,
    '-G', 'Ninja',
    '-DCMAKE_BUILD_TYPE=Release',
    "-DCMAKE_MAKE_PROGRAM=$ninja",
    "-DCMAKE_CXX_COMPILER=$cxx",
    "-DCMAKE_RC_COMPILER=$windres",
    "-DSKIA_ROOT=$skiaRoot",
    "-DELOI_STATIC_ROOT=$staticRoot",
    '-DELOI_BUILD_TESTS=ON'
  )
  Invoke-Checked $cmake @('--build', $build, '--target', 'release', 'eloi_tests', '-j', '2')
  Invoke-Checked $ctest @('--test-dir', $build, '--output-on-failure')

  $release = Join-Path $source 'dist\release'
  Assert-TwoFileRelease $release
  Assert-PeTimestampZero (Join-Path $release 'Eloi.exe')
  return $release
}

$dirty = (& git -C $projectRoot status --porcelain)
if ($LASTEXITCODE -ne 0) { throw 'Could not inspect the Git worktree' }
if ($dirty) {
  throw 'The worktree must be clean. Commit the exact source before reproducibility verification.'
}

& (Join-Path $PSScriptRoot 'verify-toolchain.ps1') -RequirePackageArchives
if ($LASTEXITCODE -ne 0) { throw 'Toolchain verification failed' }

$env:SOURCE_DATE_EPOCH = [string]$lock.source_date_epoch
$env:TZ = 'UTC'
$env:LC_ALL = 'C'

try {
  New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
  Invoke-Checked 'git.exe' @('-C', $projectRoot, 'archive', '--format=zip', '--output', $archive, 'HEAD')

  Write-Host 'Starting independent clean build A'
  $releaseA = Build-Copy 'A'
  Write-Host 'Starting independent clean build B'
  $releaseB = Build-Copy 'B'

  foreach ($name in @('Eloi.exe', 'config.yml')) {
    $left = Join-Path $releaseA $name
    $right = Join-Path $releaseB $name
    if (-not (Test-FilesEqual $left $right)) {
      throw "$name differs between independent clean builds"
    }
    $hash = (Get-FileHash -LiteralPath $left -Algorithm SHA256).Hash
    Write-Host "$name SHA-256: $hash"
  }

  if ($StageRelease) {
    $stage = Join-Path $projectRoot 'dist\release'
    $resolvedProject = [System.IO.Path]::GetFullPath($projectRoot).TrimEnd('\')
    $resolvedStage = [System.IO.Path]::GetFullPath($stage)
    if (-not $resolvedStage.StartsWith($resolvedProject + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
      throw "Refusing to stage outside the repository: $resolvedStage"
    }
    if (Test-Path -LiteralPath $resolvedStage) {
      Remove-Item -LiteralPath $resolvedStage -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $resolvedStage | Out-Null
    Copy-Item -LiteralPath (Join-Path $releaseA 'Eloi.exe') -Destination $resolvedStage
    Copy-Item -LiteralPath (Join-Path $releaseA 'config.yml') -Destination $resolvedStage
    Assert-TwoFileRelease $resolvedStage
    Write-Host "Staged verified release in $resolvedStage"
  }

  Write-Host 'SUCCESS: two independent clean builds are byte-for-byte identical.'
} finally {
  if (-not $Keep -and (Test-Path -LiteralPath $tempRoot)) {
    $resolvedTemp = [System.IO.Path]::GetFullPath($tempRoot)
    $leaf = Split-Path -Leaf $resolvedTemp
    if (-not $resolvedTemp.StartsWith($tempParent + '\', [System.StringComparison]::OrdinalIgnoreCase) -or
        -not $leaf.StartsWith('Eloi-repro-', [System.StringComparison]::Ordinal)) {
      throw "Refusing to remove unexpected temporary path: $resolvedTemp"
    }
    Remove-Item -LiteralPath $resolvedTemp -Recurse -Force
  } elseif ($Keep) {
    Write-Host "Kept independent build trees at $tempRoot"
  }
}
