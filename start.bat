@echo off
setlocal
cd /d "%~dp0"

set "PLATFORM_PYTHON="
if exist ".venv\Scripts\python.exe" set "PLATFORM_PYTHON=.venv\Scripts\python.exe" && goto launch
if exist "venv\Scripts\python.exe" set "PLATFORM_PYTHON=venv\Scripts\python.exe" && goto launch
where python >nul 2>nul
if not errorlevel 1 set "PLATFORM_PYTHON=python" && goto launch
where py >nul 2>nul
if not errorlevel 1 set "PLATFORM_PYTHON=py -3" && goto launch

echo [ERROR] Python 3.10+ was not found. Follow README Quick Start first.
if "%~1"=="" pause
exit /b 1

:launch
echo Starting A-share strategy platform (frontend + backend)...
%PLATFORM_PYTHON% web_app.py %*
if not errorlevel 1 exit /b 0
echo.
echo [ERROR] Startup failed. Review the message above.
if "%~1"=="" pause
exit /b 1
