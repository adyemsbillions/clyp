@echo off
setlocal
php -S localhost:8000 -t public public\router.php
endlocal
