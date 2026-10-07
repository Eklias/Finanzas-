@echo off
title Sistema Finanzas - FIIS UNI
color 0B
echo ========================================================
echo         SISTEMA FINANZAS - FIIS UNI
echo ========================================================
echo.
echo 1. Accediendo al directorio del proyecto...
cd /d "%~dp0"

echo 2. Iniciando el servidor Django en http://127.0.0.1:8000/ ...
echo (IMPORTANTE: Manten esta ventana abierta mientras uses el sistema)
echo.

:: Abrir el navegador en segundo plano tras 2 segundos para que Django alcance a iniciar
start "" /b cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8000/"

.\.venv\Scripts\python.exe manage.py runserver

pause
