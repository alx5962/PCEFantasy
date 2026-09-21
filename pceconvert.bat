@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ========================================================================
echo  Legend of Zelda NES ^-^> PC Engine Converter
echo ========================================================================
echo.

REM Check Python
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not on PATH.
    echo Please install Python 3.x from https://www.python.org/
    echo.
    pause
    exit /b 1
)

REM Check Pillow
python -c "import PIL" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python Pillow library is not installed.
    echo Run:  pip install pillow
    echo.
    pause
    exit /b 1
)

REM Check bundled HuCC tools
if not exist "tools\bin\hucc.exe" (
    echo ERROR: Bundled HuCC toolchain not found at tools\bin\hucc.exe
    echo The tools\ directory should have been included with this package.
    echo.
    pause
    exit /b 1
)
if not exist "tools\bin\pceas.exe" (
    echo ERROR: Bundled pceas.exe not found at tools\bin\pceas.exe
    echo.
    pause
    exit /b 1
)

echo Prerequisites OK.
echo.

REM Launch converter (GUI mode if no argument, CLI mode if argument given)
if "%~1"=="" (
    echo Opening ROM file picker...
    python pceconvert.py
) else (
    python pceconvert.py "%~1"
)

echo.
pause
