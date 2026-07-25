@echo off
setlocal
pushd "%~dp0"

echo Repairing the Clyp one-click editor database...
where php >nul 2>nul
if errorlevel 1 (
  echo.
  echo [FAIL] PHP was not found in PATH.
  popd
  exit /b 1
)

php scripts\repair_auto_editor.php
if errorlevel 1 (
  echo.
  echo [FAIL] The database repair did not complete.
  echo Read the specific error printed above.
  popd
  exit /b 1
)

echo.
echo [OK] Repair complete.
echo Restart Clyp with: .\start.bat
popd
endlocal
