@echo off
setlocal

cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON=py -3"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python 3 was not found on PATH.
        echo Install Python 3.10+ and rerun this script.
        exit /b 1
    )
    set "PYTHON=python"
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    call %PYTHON% -m venv .venv
    if errorlevel 1 exit /b 1

    echo Installing dependencies...
    call ".venv\Scripts\python.exe" -m pip install --upgrade pip
    if errorlevel 1 exit /b 1
    call ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 exit /b 1
)

if not exist ".env" (
    copy /Y ".env.example" ".env" >nul
    echo Created .env from .env.example.
    echo Add your Google API key to .env before running the pipeline.
)

if not exist "data" (
    mkdir "data"
)

findstr /B /C:"GOOGLE_API_KEY=your_api_key_here" ".env" >nul 2>nul
if %errorlevel%==0 (
    echo GOOGLE_API_KEY is still set to the placeholder value in .env.
    echo Update .env, then rerun start.bat.
    exit /b 1
)

echo Running collection...
call ".venv\Scripts\python.exe" collect.py
if errorlevel 1 exit /b 1

echo.
echo Running enrichment...
call ".venv\Scripts\python.exe" enrich.py
if errorlevel 1 exit /b 1

echo.
echo Running export...
call ".venv\Scripts\python.exe" export.py
if errorlevel 1 exit /b 1

echo.
echo Pipeline complete. Outputs are in the data folder.
endlocal
