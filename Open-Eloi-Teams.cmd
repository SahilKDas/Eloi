@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-eloi.ps1" -Mode Teams
if errorlevel 1 pause
