@echo off
cd /d "%~dp0"
echo Abriendo la demostracion con datos ficticios...
echo Direccion: http://127.0.0.1:8799/
echo Deja esta ventana abierta mientras utilizas la demo.
"%~dp0.venv\Scripts\python.exe" demo.py
pause
