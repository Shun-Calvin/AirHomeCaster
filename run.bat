@echo off
rem AirHomeCaster launcher - streams Windows audio to AirPlay devices.
rem It tries, in order: Anaconda/Miniconda installs, python.org installs,
rem then whatever pythonw.exe is on PATH. To pin a specific Python, set
rem PYTHONW_PATH below, e.g.:  set "PYTHONW_PATH=C:\Users\me\anaconda3\pythonw.exe"

setlocal enabledelayedexpansion

rem --- 1. explicit override (edit this line if needed) ---
set "PYTHONW_PATH="

rem --- 2. collect candidate pythons that ship with tkinter ---
set "CANDIDATES="
for %%D in (
    "%USERPROFILE%\anaconda3"
    "%USERPROFILE%\miniconda3"
    "%ProgramData%\anaconda3"
    "%ProgramData%\miniconda3"
    "%LOCALAPPDATA%\Programs\Python\Python312"
    "%LOCALAPPDATA%\Programs\Python\Python311"
    "%LOCALAPPDATA%\Programs\Python\Python310"
) do (
    if exist "%%~D\pythonw.exe" set "CANDIDATES=!CANDIDATES! "%%~D\pythonw.exe""
)
where pythonw.exe >nul 2>nul && set "CANDIDATES=!CANDIDATES! pythonw.exe"

rem --- 3. pick the first candidate that can import the required packages ---
for %%P in (%CANDIDATES%) do (
    "%%~P" -c "import pyatv, soundcard, scipy" >nul 2>&1
    if not errorlevel 1 (
        set "PYTHONW_PATH=%%~P"
        goto :found
    )
)

echo.
echo  [AirHomeCaster] No Python found with the required packages.
echo  Install them with:
echo      pip install pyatv soundcard scipy numpy pycaw comtypes pystray pillow
echo  Then edit run.bat and set PYTHONW_PATH to your pythonw.exe.
echo.
pause
exit /b 1

:found
cd /d "%~dp0"
start "AirHomeCaster" /D "%~dp0" "!PYTHONW_PATH!" launch.py
