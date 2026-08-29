param(
    [Parameter(Mandatory = $true)]
    [string]$ComparisonPath,
    [switch]$AllowUnknown
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $ComparisonPath)) {
    Write-Error "Comparison file not found: $ComparisonPath"
    exit 3
}

try {
    $comparison = Get-Content -LiteralPath $ComparisonPath -Raw | ConvertFrom-Json
} catch {
    Write-Error "Failed to parse comparison JSON: $ComparisonPath"
    exit 3
}

$status = [string]$comparison.acceptance_status
if (-not $status) {
    Write-Error "Missing acceptance_status in comparison JSON: $ComparisonPath"
    exit 3
}

$checks = @($comparison.acceptance_checks)
if ($checks.Count -eq 0) {
    Write-Error "Missing acceptance_checks in comparison JSON: $ComparisonPath"
    exit 3
}

$failures = @($checks | Where-Object { $_.status -eq "FAIL" })
$unknowns = @($checks | Where-Object { $_.status -eq "UNKNOWN" })
$passes = @($checks | Where-Object { $_.status -eq "PASS" })

Write-Host "Runtime acceptance: $status"
Write-Host "Checks: PASS=$($passes.Count), FAIL=$($failures.Count), UNKNOWN=$($unknowns.Count)"
Write-Host "File: $ComparisonPath"

if ($failures.Count -gt 0) {
    Write-Host ""
    Write-Host "Failures:"
    foreach ($item in $failures) {
        Write-Host "- $($item.name): expected $($item.expected); actual $($item.actual)"
    }
}

if ($unknowns.Count -gt 0) {
    Write-Host ""
    Write-Host "Unknown checks:"
    foreach ($item in $unknowns) {
        Write-Host "- $($item.name): expected $($item.expected); actual $($item.actual)"
    }
}

if ($status -eq "PASS") {
    exit 0
}

if ($status -eq "UNKNOWN" -and $AllowUnknown) {
    exit 0
}

if ($status -eq "UNKNOWN") {
    exit 2
}

exit 1
