$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$depsRoot = Join-Path $projectRoot '.deps'
$packageCache = Join-Path $depsRoot 'packages'
$skiaRoot = Join-Path $depsRoot 'skia108'
$runtimeRoot = Join-Path $depsRoot 'runtime'
$nanoSvgRoot = Join-Path $depsRoot 'nanosvg'
$repository = 'https://repo.msys2.org/mingw/ucrt64'

New-Item -ItemType Directory -Force -Path $packageCache, $skiaRoot, $runtimeRoot, $nanoSvgRoot | Out-Null

$tar = 'C:\msys64\usr\bin\tar.exe'
if (-not (Test-Path $tar)) {
  $tarCommand = Get-Command tar.exe -ErrorAction Stop
  $tar = $tarCommand.Source
}

function Install-Archive {
  param(
    [Parameter(Mandatory)] [string] $Name,
    [Parameter(Mandatory)] [string] $Destination
  )
  $archive = Join-Path $packageCache $Name
  if (-not (Test-Path $archive)) {
    Write-Host "Downloading $Name"
    Invoke-WebRequest -UseBasicParsing -Uri "$repository/$Name" -OutFile $archive
  }
  & $tar --zstd -xf $archive -C $Destination
  if ($LASTEXITCODE -ne 0) { throw "Could not extract $Name" }
}

Install-Archive 'mingw-w64-ucrt-x86_64-skia-108.0.5359.95-4-any.pkg.tar.zst' $skiaRoot

$runtimePackages = @(
  'mingw-w64-ucrt-x86_64-gcc-libs-16.2.0-3-any.pkg.tar.zst',
  'mingw-w64-ucrt-x86_64-libwinpthread-git-12.0.0.r747.g1a99f8514-1-any.pkg.tar.zst',
  'mingw-w64-ucrt-x86_64-libjpeg-turbo-3.2.0-1-any.pkg.tar.zst',
  'mingw-w64-ucrt-x86_64-libpng-1.6.58-1-any.pkg.tar.zst',
  'mingw-w64-ucrt-x86_64-libwebp-1.6.0-1-any.pkg.tar.zst',
  'mingw-w64-ucrt-x86_64-zlib-1.3.2-2-any.pkg.tar.zst'
)
foreach ($package in $runtimePackages) {
  Install-Archive $package $runtimeRoot
}

Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/memononen/nanosvg/master/src/nanosvg.h' -OutFile (Join-Path $nanoSvgRoot 'nanosvg.h')
Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/memononen/nanosvg/master/LICENSE.txt' -OutFile (Join-Path $nanoSvgRoot 'LICENSE.txt')

Write-Host 'Eloi dependencies are ready in .deps (ignored by git).'
