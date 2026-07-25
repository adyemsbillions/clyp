@echo off
setlocal
pushd "%~dp0"

where php >nul 2>nul
if errorlevel 1 (
  echo [FAIL] PHP was not found in PATH.
  echo Install PHP 8.3 or add php.exe to PATH, then run this file again.
  popd
  exit /b 1
)

if not exist .env copy .env.example .env >nul
if not exist storage mkdir storage
if not exist storage\uploads mkdir storage\uploads
if not exist storage\exports mkdir storage\exports
if not exist storage\tmp mkdir storage\tmp
if not exist storage\sounds mkdir storage\sounds

if not exist storage\sounds\afro-pulse.wav (
  where py >nul 2>nul
  if errorlevel 1 (
    echo [WARN] Python launcher "py" was not found. Skipping demo sound generation.
  ) else (
    py scripts\generate_demo_sounds.py
  )
)

php scripts\check.php
if errorlevel 1 (
  echo.
  echo Clyp setup stopped because one or more required components are missing.
  popd
  exit /b 1
)

php scripts\install.php
if errorlevel 1 (
  echo.
  echo Clyp could not install its database schema.
  popd
  exit /b 1
)

echo.
echo Clyp setup completed successfully.
echo Run .\configure-gemini.bat to add your Gemini API key.
popd
endlocal
