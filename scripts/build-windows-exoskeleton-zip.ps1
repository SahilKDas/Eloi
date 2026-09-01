param(
  [switch] $AllowDirty,
  [switch] $SkipDefenderScan,
  [string] $OutputRoot,
  [string] $CandidateLabel
)

$arguments = @{}
if ($AllowDirty) { $arguments.AllowDirty = $true }
if ($SkipDefenderScan) { $arguments.SkipDefenderScan = $true }
if ($OutputRoot) { $arguments.OutputRoot = $OutputRoot }
if ($CandidateLabel) { $arguments.CandidateLabel = $CandidateLabel }

& (Join-Path $PSScriptRoot 'build-windows-split-zip.ps1') @arguments
