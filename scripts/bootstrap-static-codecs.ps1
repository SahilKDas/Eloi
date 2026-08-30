$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$depsRoot = Join-Path $projectRoot '.deps'
$sourceRoot = Join-Path $depsRoot 'static-sources'
$buildRoot = Join-Path $depsRoot 'static-build'
$installRoot = Join-Path $depsRoot 'static-runtime'
$archiveRoot = Join-Path $depsRoot 'packages'
$lock = Get-Content -LiteralPath (Join-Path $projectRoot 'reproducibility.lock.json') -Raw |
  ConvertFrom-Json
$env:SOURCE_DATE_EPOCH = [string]$lock.source_date_epoch
$cmake = 'C:/msys64/ucrt64/bin/cmake.exe'
$ninja = 'C:/msys64/ucrt64/bin/ninja.exe'
$cc = 'C:/msys64/ucrt64/bin/cc.exe'

New-Item -ItemType Directory -Force -Path `
  $sourceRoot, $buildRoot, $installRoot, $archiveRoot | Out-Null

function Get-Source {
  param([string] $Name, [string] $LockName, [string] $Directory)
  $dependency = $lock.downloaded_dependencies | Where-Object name -eq $LockName
  if ($null -eq $dependency) { throw "No dependency lock exists for $LockName" }
  $destination = Join-Path $sourceRoot $Directory
  if (Test-Path -LiteralPath $destination) { return $destination }
  $archive = Join-Path $archiveRoot $dependency.archive
  if (-not (Test-Path -LiteralPath $archive)) {
    Write-Host "Downloading static $Name source"
    Invoke-WebRequest -UseBasicParsing -Uri $dependency.url -OutFile $archive
  }
  $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
  if ($actual -ne $dependency.sha256) {
    throw "Hash mismatch for $($dependency.archive). Expected $($dependency.sha256), got $actual"
  }
  & tar.exe --force-local -xzf $archive -C $sourceRoot
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $destination)) {
    throw "Could not extract static $Name source"
  }
  return $destination
}

function Build-Static {
  param([string] $Name, [string] $Source, [string[]] $Options)
  $build = Join-Path $buildRoot $Name
  & $cmake -S $Source -B $build -G Ninja `
    -DCMAKE_BUILD_TYPE=Release `
    "-DCMAKE_C_COMPILER=$cc" `
    "-DCMAKE_MAKE_PROGRAM=$ninja" `
    "-DCMAKE_INSTALL_PREFIX=$installRoot" `
    -DBUILD_SHARED_LIBS=OFF @Options
  if ($LASTEXITCODE -ne 0) { throw "Could not configure $Name" }
  & $cmake --build $build --target install -j 2
  if ($LASTEXITCODE -ne 0) { throw "Could not build $Name" }
}

$zlib = Get-Source zlib zlib 'zlib-1.3.2'
Build-Static zlib $zlib @('-DZLIB_BUILD_TESTING=OFF')

$jpeg = Get-Source jpeg libjpeg-turbo 'libjpeg-turbo-3.2.0'
Build-Static jpeg $jpeg @(
  '-DENABLE_SHARED=OFF',
  '-DENABLE_STATIC=ON',
  '-DWITH_JPEG8=ON',
  '-DWITH_TURBOJPEG=OFF',
  '-DWITH_TESTS=OFF'
)

$png = Get-Source png libpng 'libpng-1.6.58'
Build-Static png $png @(
  '-DPNG_SHARED=OFF',
  '-DPNG_STATIC=ON',
  '-DPNG_TESTS=OFF',
  "-DZLIB_ROOT=$installRoot"
)

$webp = Get-Source webp libwebp 'libwebp-1.6.0'
Build-Static webp $webp @(
  '-DWEBP_BUILD_ANIM_UTILS=OFF',
  '-DWEBP_BUILD_CWEBP=OFF',
  '-DWEBP_BUILD_DWEBP=OFF',
  '-DWEBP_BUILD_EXTRAS=OFF',
  '-DWEBP_BUILD_GIF2WEBP=OFF',
  '-DWEBP_BUILD_IMG2WEBP=OFF',
  '-DWEBP_BUILD_LIBWEBPMUX=ON',
  '-DWEBP_BUILD_VWEBP=OFF',
  '-DWEBP_BUILD_WEBPINFO=OFF',
  '-DWEBP_BUILD_WEBPMUX=OFF'
)

Write-Host "Static codecs installed in $installRoot"
