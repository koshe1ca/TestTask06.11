@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Semantic TextNavigator - local server
start "" "http://127.0.0.1:8501"
where py >nul 2>&1
if %errorlevel%==0 (
    py -3 server.py
) else (
    python server.py
)
echo.
echo If Python is missing, install Python 3.10+ and retry.
pause
