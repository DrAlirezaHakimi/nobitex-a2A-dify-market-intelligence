@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -m pip install -r requirements.txt
if errorlevel 1 (echo Could not install dependencies. & pause & exit /b 1)
py -m app.bootstrap
pause
