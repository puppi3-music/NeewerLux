@echo off
REM Puppi3's NeewerLux - HTTP Server Only (no GUI)

title Puppi3's NeewerLux HTTP Server
cd /d "%~dp0"

echo ====================================================
echo   Puppi3's NeewerLux - HTTP Server Mode
echo   Web dashboard: http://localhost:8080/
echo   API endpoint:  http://localhost:8080/Puppi3sNeewerLux/doAction?
echo   (8080 is the default; use your own port if you changed it
echo   in Global Preferences)
echo   Press Ctrl+C to stop
echo ====================================================
echo.

python Puppi3sNeewerLux.py --http %*
