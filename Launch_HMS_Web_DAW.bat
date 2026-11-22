@echo off
title 337 West Productions - HMS Unified Studio Suite (v1.4 Web-DAW)
cd /d "C:\github\projects\hms-stem-cleaner"

set "WV2_CACHE=%LOCALAPPDATA%\HMS Studio Suite\WebView2Cache"
if not exist "%WV2_CACHE%" mkdir "%WV2_CACHE%"
set "WEBVIEW2_USER_DATA_FOLDER=%WV2_CACHE%"
set "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--disable-gpu-compositing"

where python.exe >nul 2>&1
if %errorlevel%==0 (
    set "PY_CMD=python.exe"
) else if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" (
    set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
) else (
    set "PY_CMD=py -3"
)

echo [RUN] Launching HMS Unified Studio Suite from hms_web_daw_launcher.py...
%PY_CMD% "C:\github\projects\hms-stem-cleaner\hms_web_daw_launcher.py"

if errorlevel 1 (
    echo.
    echo [ERROR] Launcher exited with code %errorlevel%. Review the traceback above.
    pause
)
