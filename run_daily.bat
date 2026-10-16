@echo off
REM Ежедневный запуск автотестов RGB ERP — для Планировщика заданий Windows.
REM Можно передать модули: run_daily.bat contacts smeta
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
py -3 run_all.py %*
exit /b %ERRORLEVEL%
