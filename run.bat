@echo off
"%~dp0.venv\Scripts\python.exe" "%~dp0app.py" %*
if errorlevel 1 pause
