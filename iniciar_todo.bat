@echo off
title Guia Interrapidisimo - Lanzador
echo ============================================================
echo   Iniciando Guia Interrapidisimo (admin + publico a la vez)
echo ============================================================
echo.

cd /d "%~dp0"

start "Interrapidisimo - ADMIN" cmd /k python servidor_admin.py
timeout /t 2 /nobreak >nul
start "Interrapidisimo - PUBLICO" cmd /k python servidor_publico.py

echo.
echo Los dos servidores se estan abriendo en sus propias ventanas.
echo Puedes cerrar esta ventana.
echo.
pause >nul
