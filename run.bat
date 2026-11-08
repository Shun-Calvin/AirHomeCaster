@echo off
rem AirHomeCaster launcher - streams Windows audio to AirPlay devices
rem Adjust PYTHONW to your Python that has tkinter (e.g. Anaconda).
setlocal
set "PYTHONW=pythonw.exe"
where pythonw.exe >nul 2>nul && set "PYTHONW=pythonw.exe"
if exist "%LOCALAPPDATA%\Programs\Python\Python3*\pythonw.exe" (
    for /f "delims=" %%P in ('dir /b /o-n "%LOCALAPPDATA%\Programs\Python\Python3*\pythonw.exe" 2^>nul') do (
        set "PYTHONW=%LOCALAPPDATA%\Programs\Python\%%~P"
        goto :found
    )
)
:found
cd /d "%~dp0"
start "AirHomeCaster" /D "%~dp0" "%PYTHONW%" launch.py
