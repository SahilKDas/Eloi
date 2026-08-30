param(
  [string]$Executable = "",
  [string]$Label = ""
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if (-not $Executable) {
  $Executable = Join-Path $projectRoot 'build-release\Eloi.exe'
}
$source = (Resolve-Path -LiteralPath $Executable).Path
$sourceItem = Get-Item -LiteralPath $source
if ($sourceItem.PSIsContainer -or $sourceItem.Extension -ne '.exe') {
  throw "Baseline source must be an Eloi executable: $source"
}

$destination = Join-Path $sourceItem.DirectoryName 'Eloi.previous.exe'
if ($source -eq $destination) {
  throw 'The source executable is already the previous baseline.'
}
Copy-Item -LiteralPath $source -Destination $destination -Force

if (-not $Label) {
  $Label = (& git -C $projectRoot rev-parse --short=12 HEAD).Trim()
  if ($LASTEXITCODE -ne 0 -or -not $Label) {
    throw 'Could not determine the current Git commit for the baseline label.'
  }
}
$metadata = Join-Path $sourceItem.DirectoryName 'Eloi.previous.commit.txt'
Set-Content -LiteralPath $metadata -Value $Label -Encoding ascii -NoNewline

$hash = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
Write-Host "Captured the one retained brain baseline:"
Write-Host "  executable: $destination"
Write-Host "  label:      $Label"
Write-Host "  SHA-256:    $hash"
