param(
  [string] $CandidateRoot = 'tmp\nnue-training',
  [string] $OutputRoot = 'tmp\nnue-playoff',
  [string] $Manifest = 'data\nnue_candidate_builds.json'
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$candidateRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot $CandidateRoot))
$outputRoot = [IO.Path]::GetFullPath((Join-Path $projectRoot $OutputRoot))
$manifestPath = [IO.Path]::GetFullPath((Join-Path $projectRoot $Manifest))
$weightsPath = Join-Path $projectRoot 'include\eloi\nnue_weights.hpp'
$architecturePath = Join-Path $projectRoot 'include\eloi\nnue_architecture.hpp'
$comparisonPath = Join-Path $projectRoot 'data\nnue_training_comparison.json'
$cmake = 'C:/msys64/ucrt64/bin/cmake.exe'
$ctest = 'C:/msys64/ucrt64/bin/ctest.exe'
$ninja = 'C:/msys64/ucrt64/bin/ninja.exe'
$cxx = 'C:/msys64/ucrt64/bin/c++.exe'
$windres = 'C:/msys64/ucrt64/bin/windres.exe'
$python = 'python'
$lock = Get-Content (Join-Path $projectRoot 'reproducibility.lock.json') -Raw |
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

function Get-Hash {
  param([string] $Path)
  (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash
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

$initialStatus = @(& git -C $projectRoot status --porcelain)
$allowedBootstrapEntry = '?? scripts/build-nnue-candidates.ps1'
$unexpectedInitialStatus = @(
  $initialStatus | Where-Object { $_ -ne $allowedBootstrapEntry }
)
if ($unexpectedInitialStatus.Count) {
  throw (
    'Candidate builds require a clean worktree; unexpected entries: ' +
    ($unexpectedInitialStatus -join ', ')
  )
}
$null = Assert-UnderProject $candidateRoot
$null = Assert-UnderProject $outputRoot
$null = Assert-UnderProject $manifestPath

$comparison = Get-Content -LiteralPath $comparisonPath -Raw | ConvertFrom-Json
$comparisonHash = Get-Hash $comparisonPath
$sourceCommit = (& git -C $projectRoot rev-parse HEAD).Trim()
$originalWeightsHash = Get-Hash $weightsPath
$originalArchitectureHash = Get-Hash $architecturePath
$backupRoot = Join-Path $projectRoot 'tmp\nnue-build-backup'
Remove-SafeDirectory $backupRoot
New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
Copy-Item -LiteralPath $weightsPath -Destination $backupRoot
Copy-Item -LiteralPath $architecturePath -Destination $backupRoot
Remove-SafeDirectory $outputRoot
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null

& (Join-Path $PSScriptRoot 'verify-toolchain.ps1') -RequirePackageArchives
if ($LASTEXITCODE -ne 0) { throw 'Pinned toolchain verification failed' }
$env:SOURCE_DATE_EPOCH = [string]$lock.source_date_epoch
$documents = @()

try {
  foreach ($hidden in @(64, 128)) {
    $sourceCandidate = Join-Path $candidateRoot "candidate-$hidden"
    $candidateWeights = Join-Path $sourceCandidate 'nnue_weights.hpp'
    $candidateArchitecture = Join-Path $sourceCandidate 'nnue_architecture.hpp'
    $candidateProvenance = Join-Path $sourceCandidate 'provenance.json'
    foreach ($required in @($candidateWeights, $candidateArchitecture, $candidateProvenance)) {
      if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
        throw "Missing candidate input: $required"
      }
    }
    $expected = $comparison.candidates | Where-Object hidden -eq $hidden
    if ((Get-Hash $candidateWeights) -ne $expected.weights_sha256) {
      throw "Candidate $hidden weights do not match comparison provenance"
    }

    Copy-Item -LiteralPath $candidateWeights -Destination $weightsPath -Force
    Copy-Item -LiteralPath $candidateArchitecture -Destination $architecturePath -Force
    $changed = @(& git -C $projectRoot diff --name-only)
    $unexpected = @($changed | Where-Object {
      $_ -notin @(
        'include/eloi/nnue_weights.hpp',
        'include/eloi/nnue_architecture.hpp'
      )
    })
    if ($unexpected.Count) {
      throw "Unexpected source differences for candidate ${hidden}: $($unexpected -join ', ')"
    }

    $buildRoot = Join-Path $projectRoot "build-nnue-$hidden"
    Remove-SafeDirectory $buildRoot
    Invoke-Checked $cmake @(
      '-S', $projectRoot,
      '-B', $buildRoot,
      '-G', 'Ninja',
      '-DCMAKE_BUILD_TYPE=Release',
      "-DCMAKE_MAKE_PROGRAM=$ninja",
      "-DCMAKE_CXX_COMPILER=$cxx",
      "-DCMAKE_RC_COMPILER=$windres",
      '-DELOI_BUILD_TESTS=ON'
    )
    Invoke-Checked $cmake @(
      '--build', $buildRoot, '--target', 'Eloi', 'eloi_tests', '-j', '2'
    )
    Invoke-Checked $ctest @('--test-dir', $buildRoot, '--output-on-failure')

    $builtExe = Join-Path $buildRoot 'Eloi.exe'
    Assert-ZeroPeTimestamp $builtExe
    Invoke-Checked $builtExe @('--perft', '--depth', '4')
    Invoke-Checked $builtExe @('--bench', '--depth', '6')
    $differential = Join-Path $outputRoot "differential-$hidden.json"
    Invoke-Checked $python @(
      (Join-Path $PSScriptRoot 'differential_movegen.py'),
      '--engine', $builtExe,
      '--samples', '32',
      '--output', $differential
    )

    $outputExe = Join-Path $outputRoot "Eloi-nnue-$hidden.exe"
    Copy-Item -LiteralPath $builtExe -Destination $outputExe
    $documents += [ordered]@{
      hidden = $hidden
      source_commit = $sourceCommit
      weights_sha256 = Get-Hash $candidateWeights
      architecture_sha256 = Get-Hash $candidateArchitecture
      training_provenance_sha256 = Get-Hash $candidateProvenance
      executable_sha256 = Get-Hash $outputExe
      differential_report_sha256 = Get-Hash $differential
      ctest_passed = $true
      perft_depth_4_passed = $true
      benchmark_depth_6_passed = $true
      differential_positions = 96
      zero_pe_timestamp = $true
    }
  }
} finally {
  Copy-Item -LiteralPath (Join-Path $backupRoot 'nnue_weights.hpp') `
    -Destination $weightsPath -Force
  Copy-Item -LiteralPath (Join-Path $backupRoot 'nnue_architecture.hpp') `
    -Destination $architecturePath -Force
  Remove-SafeDirectory $backupRoot
}

if ((Get-Hash $weightsPath) -ne $originalWeightsHash -or
    (Get-Hash $architecturePath) -ne $originalArchitectureHash) {
  throw 'Production NNUE headers were not restored exactly'
}
if (& git -C $projectRoot status --porcelain --untracked-files=no) {
  throw 'Tracked source changed during candidate builds'
}

$manifestDocument = [ordered]@{
  schema = 1
  source_commit = $sourceCommit
  comparison_provenance_sha256 = $comparisonHash
  settings = [ordered]@{
    build_type = 'Release'
    threads = 3
    hash_mb = 32
    own_book = $false
  }
  candidates = $documents
}
$manifestDirectory = Split-Path -Parent $manifestPath
New-Item -ItemType Directory -Force -Path $manifestDirectory | Out-Null
[IO.File]::WriteAllText(
  $manifestPath,
  ($manifestDocument | ConvertTo-Json -Depth 6) + "`n",
  [Text.UTF8Encoding]::new($false)
)
Write-Host "NNUE candidate manifest: $manifestPath"
foreach ($document in $documents) {
  Write-Host "  $($document.hidden): $($document.executable_sha256)"
}
