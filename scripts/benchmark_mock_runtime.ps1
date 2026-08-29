param(
    [Parameter(Mandatory = $true)]
    [string]$PythonPath,
    [Parameter(Mandatory = $true)]
    [string]$Label,
    [int]$Port = 8770,
    [int]$DurationSeconds = 12,
    [string]$CameraId = "camera_01",
    [string]$SourceUrl = "mock://colorbars",
    [switch]$SkipBinary,
    [string]$OutputDir = "artifacts/environment_audit"
)

$Script = Join-Path (Split-Path -Parent $PSCommandPath) "benchmark_runtime.ps1"
$params = @{
    PythonPath = $PythonPath
    Label = $Label
    Port = $Port
    DurationSeconds = $DurationSeconds
    CameraId = $CameraId
    SourceUrl = $SourceUrl
    OutputDir = $OutputDir
}
if ($SkipBinary) {
    $params.SkipBinary = $true
}

& $Script @params
exit $LASTEXITCODE
