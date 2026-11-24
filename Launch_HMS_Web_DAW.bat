@echo off
title 337 West Productions - HMS Unified Studio Suite (v1.4 Web-DAW)
cd /d "C:\github\projects\hms-stem-cleaner"

:: Route WebView2 cache to writable %LOCALAPPDATA% and prevent GPU dark-lock
set "WV2_CACHE=%LOCALAPPDATA%\HMS Studio Suite\WebView2Cache"
if not exist "%WV2_CACHE%" mkdir "%WV2_CACHE%"
set "WEBVIEW2_USER_DATA_FOLDER=%WV2_CACHE%"
set "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--disable-gpu-compositing"

:: Prioritize verified Python 3.14, then PATH python.exe, then py launcher
set "SCRIPT=C:\github\projects\hms-stem-cleaner\hms_web_daw_launcher.py"
set "PY314=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"

echo [RUN] Launching HMS Unified Studio Suite from hms_web_daw_launcher.py...

if exist "%PY314%" (
    "%PY314%" -u "%SCRIPT%"
    goto :check_err
)

where python.exe >nul 2>&1
if errorlevel 1 (
    py -3 -u "%SCRIPT%"
) else (
    python.exe -u "%SCRIPT%"
)

:check_err
if errorlevel 1 (
    echo.
    echo [ERROR] Launcher exited with code %errorlevel%. Review the traceback above.
    pause
)
