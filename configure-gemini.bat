@echo off
setlocal
pushd "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\configure_gemini.ps1"
set CODE=%ERRORLEVEL%
popd
exit /b %CODE%
