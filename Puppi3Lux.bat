@echo off
REM Puppi3Lux Windows launcher (no console window)
REM Uses pythonw.exe so no command prompt window appears.
REM For debugging with console output, run: python Puppi3Lux.py

cd /d "%~dp0"

REM Try pythonw first (no console), fall back to python
where pythonw >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    start "" pythonw "%~dp0Puppi3Lux.py" %*
) else (
    start "" python "%~dp0Puppi3Lux.py" %*
)
