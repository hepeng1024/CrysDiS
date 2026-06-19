$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$Python = if ($env:PYTHON) { $env:PYTHON } else { "python" }
$PythonPrefix = & $Python -c "import sys; print(sys.prefix)"
$CondaLibraryBin = Join-Path $PythonPrefix "Library\bin"

$PyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onedir",
    "--windowed",
    "--name", "CrysDiS",
    "--icon", "assets\CrysDiS.ico",
    "--add-data", "assets;assets",
    "--add-data", "custom_crystals_local.json;.",
    "--hidden-import", "webview",
    "--collect-all", "nicegui",
    "--collect-data", "pymatgen",
    "--collect-data", "periodictable"
)

if (Test-Path $CondaLibraryBin) {
    $PyInstallerArgs += @(
        "--paths", $CondaLibraryBin,
        "--add-binary", "$CondaLibraryBin\*.dll;."
    )
}

$PyInstallerArgs += "CrysDiS.py"

& $Python -m PyInstaller @PyInstallerArgs
