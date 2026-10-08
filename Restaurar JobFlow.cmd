@echo off
cd /d "%~dp0"
echo Preparando JobFlow en este ordenador...
where py >nul 2>nul
if errorlevel 1 (
  python scripts\restore.py
) else (
  py -3 scripts\restore.py
)
if errorlevel 1 (
  echo No se pudo completar la instalacion. Comprueba que tienes Python 3.11 o posterior y conexion a Internet.
)
pause
