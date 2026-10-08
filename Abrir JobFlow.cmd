@echo off
cd /d "%~dp0"
echo Abriendo JobFlow AI...
echo Deja esta ventana abierta mientras usas la aplicacion.
"%~dp0.venv\Scripts\python.exe" run.py
echo.
echo La aplicacion se ha detenido.
pause
