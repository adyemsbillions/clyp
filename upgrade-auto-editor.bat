@echo off
setlocal
pushd "%~dp0"

echo Updating the Clyp database schema...
php scripts\repair_auto_editor.php
if errorlevel 1 (
  echo.
  echo [FAIL] The database upgrade did not complete.
  popd
  exit /b 1
)

echo.
echo Checking the one-click editor requirements...
php scripts\check.php
if errorlevel 1 (
  echo.
  echo [WARN] Fix the failed checks above before rendering with the auto editor.
  popd
  exit /b 1
)

echo.
echo [OK] Clyp One-Click Editor is ready.
echo Start it with: .\start.bat
popd
endlocal
