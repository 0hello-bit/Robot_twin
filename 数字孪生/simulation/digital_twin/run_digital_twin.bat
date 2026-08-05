@echo off
chcp 65001 >nul
cd /d "%~dp0"
"D:\python3.7\python.exe" main.py
if errorlevel 1 pause
