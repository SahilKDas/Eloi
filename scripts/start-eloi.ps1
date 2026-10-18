param(
    [ValidateSet('Teams', 'Operations')][string]$Mode = 'Teams',
    [string]$Config,
    [switch]$Check
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$engine = Join-Path $projectRoot 'target\release\eloi-rs.exe'
if (-not (Test-Path -LiteralPath $engine)) { throw 'Build the Rust application first: cargo build --release -p eloi-rs --offline' }
$identity = & $engine --version
if ($LASTEXITCODE -ne 0) { throw 'Unable to read Rust executable identity.' }
$versionLine = Select-String -LiteralPath (Join-Path $projectRoot 'Cargo.toml') -Pattern '^version = "([^"]+)"$' | Select-Object -First 1
if (-not $versionLine -or $identity -ne "Eloi $($versionLine.Matches[0].Groups[1].Value)") {
    throw 'Executable version differs from this source tree. Rebuild the Rust application first.'
}
Write-Host $identity
if ($Mode -eq 'Teams') {
    if (-not $Check) { & $engine --four-player-gui }
    exit $LASTEXITCODE
}
$donor = Join-Path $projectRoot '.deps\caissa-2.0\caissa-2.0-x64-avx2.exe'
$expected = '043C0925DF8C608D0D87B9E6B1C761240DDD1901EE8CBA49E346686B28816B97'
if (-not (Test-Path -LiteralPath $donor) -or (Get-FileHash -LiteralPath $donor -Algorithm SHA256).Hash -ne $expected) {
    throw 'Verified Caissa 2.0 AVX2 worker is missing or its hash differs; bridge launch refused.'
}
if (-not $Config) {
    # Reuse the already validated native config without copying or printing its token.
    $Config = Join-Path $projectRoot '.deps\lichess-bot\engines\Eloi-v3.6.0-live\config.yml'
}
& $engine --check-config --config $Config
if ($LASTEXITCODE -ne 0) { throw 'Native configuration rejected; no connection started.' }
Write-Host 'Standard route: hash-verified Caissa 2.0; native variants retain their Eloi routes.'
if ($Check) { Write-Host 'Offline validation only: no bridge connection started.'; exit 0 }
# Detect old C++ bridges as well as Rust Operations Center instances. Never kill them.
try { $processes = @(Get-CimInstance Win32_Process -ErrorAction Stop) }
catch { throw 'Cannot inspect running processes. Bridge launch refused; use this launcher in your normal desktop PowerShell session.' }
$bridges = @($processes | Where-Object {
    $_.Name -eq 'EloiLichess.exe' -or
    ($_.Name -in @('eloi-rs.exe','Eloi.exe') -and
        (-not $_.CommandLine -or $_.CommandLine -match '--operations-center|--lichess|--internal-caissa-worker'))
})
if ($bridges.Count -gt 0) {
    throw 'An Eloi bridge is already open. Finish the active game and close that bridge, then run this launcher again. Nothing was stopped.'
}
Write-Host "Starting Operations Center from $engine"
& $engine --operations-center --config $Config --donor-worker $donor
exit $LASTEXITCODE
