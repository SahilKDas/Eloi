param(
  [switch] $AllowDirty,
  [switch] $SkipDefenderScan,
  [string] $OutputRoot,
  [string] $CandidateLabel
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$cmakeSource = Get-Content -LiteralPath (Join-Path $projectRoot 'CMakeLists.txt') -Raw
if ($cmakeSource -notmatch 'project\(Eloi VERSION ([0-9]+\.[0-9]+\.[0-9]+)') {
  throw 'Could not determine Eloi version from CMakeLists.txt'
}
$releaseVersion = $Matches[1]
if ($cmakeSource -match 'set\(ELOI_PRERELEASE "([^"]*)"\)' -and $Matches[1]) {
  $releaseVersion += '-' + $Matches[1]
}
if ($CandidateLabel) {
  if ($CandidateLabel -notmatch '^[A-Za-z0-9][A-Za-z0-9.-]*$') {
    throw 'CandidateLabel may contain only letters, numbers, dots, and hyphens.'
  }
  $releaseVersion += '-' + $CandidateLabel
}
$packageName = "Eloi-v$releaseVersion-windows-x64-exoskeleton"
$buildRoot = Join-Path $projectRoot 'build-split-runtime'
if ($OutputRoot) {
  $outputRoot = [IO.Path]::GetFullPath($OutputRoot)
} else {
  $outputRoot = Join-Path $projectRoot 'dist\exoskeleton'
}
$packageRoot = Join-Path $outputRoot $packageName
$zipPath = Join-Path $outputRoot ($packageName + '.zip')
$cmake = 'C:/msys64/ucrt64/bin/cmake.exe'
$ctest = 'C:/msys64/ucrt64/bin/ctest.exe'
$ninja = 'C:/msys64/ucrt64/bin/ninja.exe'
$cxx = 'C:/msys64/ucrt64/bin/c++.exe'
$windres = 'C:/msys64/ucrt64/bin/windres.exe'
$objdump = 'C:/msys64/ucrt64/bin/objdump.exe'
$lock = Get-Content -LiteralPath (Join-Path $projectRoot 'reproducibility.lock.json') -Raw |
  ConvertFrom-Json

function Assert-UnderProject {
  param([string] $Path)
  $root = [IO.Path]::GetFullPath($projectRoot).TrimEnd('\')
  $resolved = [IO.Path]::GetFullPath($Path)
  if (-not $resolved.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw "Path escapes the repository: $resolved"
  }
  return $resolved
}

function Remove-SafeDirectory {
  param([string] $Path)
  $resolved = Assert-UnderProject $Path
  if (Test-Path -LiteralPath $resolved) {
    Remove-Item -LiteralPath $resolved -Recurse -Force
  }
}

function Invoke-Checked {
  param([string] $FilePath, [string[]] $Arguments)
  & $FilePath @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "$FilePath failed with exit code $LASTEXITCODE"
  }
}

function Get-Imports {
  param([string] $Path)
  @(& $objdump -p $Path |
      Select-String 'DLL Name:\s*(.+)$' |
      ForEach-Object { $_.Matches[0].Groups[1].Value.Trim() })
}

function Assert-ZeroPeTimestamp {
  param([string] $Path)
  $stream = [IO.File]::OpenRead($Path)
  $reader = [IO.BinaryReader]::new($stream)
  try {
    $stream.Position = 0x3c
    $offset = $reader.ReadInt32()
    $stream.Position = $offset + 8
    if ($reader.ReadUInt32() -ne 0) { throw "$Path has a nonzero PE timestamp" }
  } finally {
    $reader.Dispose()
    $stream.Dispose()
  }
}

function Invoke-UciHandshake {
  param([string] $Path)
  $startInfo = New-Object System.Diagnostics.ProcessStartInfo
  $startInfo.FileName = $Path
  $startInfo.Arguments = '--uci'
  $startInfo.UseShellExecute = $false
  $startInfo.CreateNoWindow = $true
  $startInfo.RedirectStandardInput = $true
  $startInfo.RedirectStandardOutput = $true
  $startInfo.RedirectStandardError = $true
  $process = New-Object System.Diagnostics.Process
  $process.StartInfo = $startInfo
  try {
    if (-not $process.Start()) { throw "Could not start $Path" }
    $process.StandardInput.WriteLine('uci')
    $process.StandardInput.WriteLine('isready')
    $process.StandardInput.WriteLine('quit')
    $process.StandardInput.Close()
    if (-not $process.WaitForExit(30000)) {
      $process.Kill()
      throw "UCI handshake timed out for $Path"
    }
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    if ($process.ExitCode -ne 0 -or
        $stdout -notmatch 'uciok' -or $stdout -notmatch 'readyok') {
      throw "UCI handshake failed for $Path (exit $($process.ExitCode))`n$stdout`n$stderr"
    }
  } finally {
    $process.Dispose()
  }
}

if (-not $AllowDirty -and (& git -C $projectRoot status --porcelain)) {
  throw 'Commit the exact source first; the Exoskeleton ZIP packager requires a clean worktree.'
}
$null = Assert-UnderProject $outputRoot

& (Join-Path $PSScriptRoot 'verify-toolchain.ps1') -RequirePackageArchives
if ($LASTEXITCODE -ne 0) { throw 'Pinned input verification failed' }

$env:SOURCE_DATE_EPOCH = [string]$lock.source_date_epoch
Remove-SafeDirectory $buildRoot
Remove-SafeDirectory $packageRoot
New-Item -ItemType Directory -Force -Path $outputRoot, $packageRoot | Out-Null
if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }

Invoke-Checked $cmake @(
  '-S', $projectRoot,
  '-B', $buildRoot,
  '-G', 'Ninja',
  '-DCMAKE_BUILD_TYPE=Release',
  "-DCMAKE_MAKE_PROGRAM=$ninja",
  "-DCMAKE_CXX_COMPILER=$cxx",
  "-DCMAKE_RC_COMPILER=$windres",
  '-DELOI_BUILD_TESTS=ON',
  '-DELOI_SPLIT_PACKAGE=ON'
)
Invoke-Checked $cmake @(
  '--build', $buildRoot, '--target', 'Eloi', 'EloiLichess', 'eloi_tests', '-j', '2'
)
Invoke-Checked $ctest @('--test-dir', $buildRoot, '--output-on-failure')

Copy-Item -LiteralPath (Join-Path $buildRoot 'Eloi.exe') -Destination $packageRoot
Copy-Item -LiteralPath (Join-Path $buildRoot 'EloiLichess.exe') -Destination $packageRoot
Copy-Item -LiteralPath (Join-Path $projectRoot 'config.example.yml') `
  -Destination (Join-Path $packageRoot 'config.yml')
Copy-Item -LiteralPath (Join-Path $projectRoot 'packaging\WINDOWS-X64-EXOSKELETON.md') `
  -Destination (Join-Path $packageRoot 'README.md')

$assetParent = Join-Path $packageRoot 'assets'
New-Item -ItemType Directory -Force -Path $assetParent | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'assets\chess_maestro_bw') `
  -Destination $assetParent -Recurse

$licenseRoot = Join-Path $packageRoot 'licenses'
New-Item -ItemType Directory -Force -Path $licenseRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $projectRoot 'LICENSE') `
  -Destination (Join-Path $licenseRoot 'Eloi-MIT.txt')
Copy-Item -LiteralPath 'C:\msys64\ucrt64\share\licenses\gcc-libs' `
  -Destination (Join-Path $licenseRoot 'gcc-libs') -Recurse
Copy-Item -LiteralPath 'C:\msys64\ucrt64\share\licenses\libwinpthread' `
  -Destination (Join-Path $licenseRoot 'libwinpthread') -Recurse
Copy-Item -LiteralPath (Join-Path $projectRoot '.deps\skia108\ucrt64\share\licenses\skia') `
  -Destination (Join-Path $licenseRoot 'skia') -Recurse
$codecLicenses = @{
  'zlib.txt' = '.deps\static-sources\zlib-1.3.2\LICENSE'
  'libjpeg-turbo.md' = '.deps\static-sources\libjpeg-turbo-3.2.0\LICENSE.md'
  'libpng.txt' = '.deps\static-sources\libpng-1.6.58\LICENSE'
  'libwebp.txt' = '.deps\static-sources\libwebp-1.6.0\COPYING'
}
foreach ($entry in $codecLicenses.GetEnumerator()) {
  Copy-Item -LiteralPath (Join-Path $projectRoot $entry.Value) `
    -Destination (Join-Path $licenseRoot $entry.Key)
}

foreach ($runtime in $lock.toolchain_runtime_libraries) {
  Copy-Item -LiteralPath $runtime.path -Destination $packageRoot
}

$mainExe = Join-Path $packageRoot 'Eloi.exe'
$lichessExe = Join-Path $packageRoot 'EloiLichess.exe'
$mainImports = Get-Imports $mainExe
$lichessImports = Get-Imports $lichessExe
if ($mainImports -contains 'WINHTTP.dll') {
  throw 'Networking was not isolated: Eloi.exe still imports WINHTTP.dll'
}
if ($lichessImports -notcontains 'WINHTTP.dll') {
  throw 'EloiLichess.exe does not import its expected WinHTTP dependency'
}
foreach ($runtime in $lock.toolchain_runtime_libraries) {
  $name = Split-Path -Leaf $runtime.path
  if ($mainImports -notcontains $name -or $lichessImports -notcontains $name) {
    throw "Expected runtime import is missing: $name"
  }
}
if (@(Get-ChildItem -LiteralPath (Join-Path $packageRoot 'assets\chess_maestro_bw') `
      -File -Filter '*.png').Count -ne 12) {
  throw 'The package must contain exactly twelve external piece PNGs'
}
Assert-ZeroPeTimestamp $mainExe
Assert-ZeroPeTimestamp $lichessExe

Invoke-UciHandshake $mainExe
& $lichessExe --check-config
if ($LASTEXITCODE -ne 0) { throw 'Exoskeleton Lichess config check failed' }
$savedErrorPreference = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
$mainLichess = & $mainExe --lichess 2>&1
$mainLichessExitCode = $LASTEXITCODE
$ErrorActionPreference = $savedErrorPreference
if ($mainLichessExitCode -ne 2 -or
    ($mainLichess -join "`n") -notmatch 'EloiLichess.exe') {
  throw 'Main executable did not redirect native Lichess users to the bridge'
}
$smoke = Join-Path $outputRoot 'exoskeleton-gui-smoke.bmp'
& $mainExe --screenshot $smoke
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $smoke)) {
  throw 'Exoskeleton GUI/assets screenshot smoke test failed'
}
Remove-Item -LiteralPath $smoke -Force

$commit = (& git -C $projectRoot rev-parse HEAD).Trim()
if (& git -C $projectRoot status --porcelain) { $commit += '-dirty' }
[IO.File]::WriteAllText(
  (Join-Path $packageRoot 'SOURCE_COMMIT.txt'),
  "$commit`n",
  [Text.UTF8Encoding]::new($false))

$manifestPath = Join-Path $packageRoot 'SHA256SUMS.txt'
$manifest = foreach ($file in Get-ChildItem -LiteralPath $packageRoot -File -Recurse |
    Where-Object FullName -ne $manifestPath | Sort-Object FullName) {
  # Windows PowerShell 5.1 runs on a framework without Path.GetRelativePath.
  # Every enumerated file is already a descendant of the absolute package root.
  $relative = $file.FullName.Substring($packageRoot.Length).TrimStart('\', '/').Replace('\', '/')
  $hash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
  "$hash  $relative"
}
[IO.File]::WriteAllLines(
  $manifestPath, $manifest, [Text.UTF8Encoding]::new($false))

Compress-Archive -Path (Join-Path $packageRoot '*') `
  -DestinationPath $zipPath -CompressionLevel Optimal

if (-not $SkipDefenderScan) {
  $scanner = 'C:\Program Files\Windows Defender\MpCmdRun.exe'
  foreach ($path in @($mainExe, $lichessExe, $zipPath)) {
    & $scanner -Scan -ScanType 3 -File $path -DisableRemediation
    if ($LASTEXITCODE -ne 0) { throw "Defender scan failed for $path" }
  }
}

$zipHash = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
$reportedMainImports = $mainImports -join ', '
$reportedLichessImports = $lichessImports -join ', '
Remove-SafeDirectory $packageRoot
Write-Host "Exoskeleton ZIP: $zipPath"
Write-Host "SHA-256: $zipHash"
Write-Host "Main imports: $reportedMainImports"
Write-Host "Lichess imports: $reportedLichessImports"
