$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$CondaPython = Join-Path $ProjectRoot '.conda\python.exe'
$ScriptsDir = Join-Path $ProjectRoot '.conda\Scripts'

if (Test-Path -LiteralPath $CondaPython) {
    $env:Path = "$ScriptsDir;$env:Path"
    Write-Host "NovelLoom project Conda environment is active for this session." -ForegroundColor Green
    & $CondaPython --version
    Write-Host "Start the Web UI with: ng serve" -ForegroundColor Cyan
} else {
    Write-Host "No .conda environment found." -ForegroundColor Yellow
    Write-Host "Create it with: conda create --prefix ./.conda python=3.11 pip -y"
    Write-Host "Then install: ./.conda/python.exe -m pip install -e `".[dev]`""
}
