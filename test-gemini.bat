@echo off
setlocal
pushd "%~dp0"
php scripts\test_gemini.php
set CODE=%ERRORLEVEL%
popd
exit /b %CODE%
