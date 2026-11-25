$ErrorActionPreference = 'Stop'
$Project = Split-Path -Parent $PSScriptRoot
Push-Location $Project
try {
    $WebSource = Join-Path $Project 'src/app/ui/streamlit_app.py'
    & '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm --onefile --windowed `
        --name RutasCiclistas --specpath build --workpath build --distpath dist `
        --paths src --collect-all streamlit --collect-all streamlit_folium `
        --hidden-import app.ui.streamlit_app `
        --recursive-copy-metadata streamlit --copy-metadata osmnx `
        --add-data "${WebSource}:web" scripts/desktop_entry.py
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo generar RutasCiclistas.exe.' }
} finally {
    Pop-Location
}
