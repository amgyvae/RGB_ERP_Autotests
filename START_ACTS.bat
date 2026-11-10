@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo Проверка доступа к чек-листу...
py -u check_checklist.py
if errorlevel 1 goto failed
echo Запуск тестов с автозаписью в чек-лист...
py -u run_all.py acts
if errorlevel 1 goto failed
echo Готово. Проверьте результаты в чек-листе и папке logs.
pause
exit /b 0
:failed
echo Есть ошибка. Передайте последние строки этого окна и свежий лог из папки logs.
pause
exit /b 1
