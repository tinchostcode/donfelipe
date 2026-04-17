@echo off
title Don Felipe — Sistema de Gestión
color 0A
cls

echo.
echo  =====================================================
echo    🐟  Don Felipe — Sistema de gestion de pescaderia
echo  =====================================================
echo.

:: ── Variables de entorno ──────────────────────────────
set DATABASE_URL=postgresql://postgres:domi.kero@localhost:5432/donfelipe
set SECRET_KEY=donfelipe-local-2026
set GEMINI_API_KEY=AIzaTU_KEY_AQUI

:: ── Verificar Python ──────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python no encontrado. Instala Python desde python.org
    pause
    exit /b 1
)

:: ── Verificar PostgreSQL ──────────────────────────────
pg_isready -U postgres -q >nul 2>&1
if errorlevel 1 (
    echo  [AVISO] PostgreSQL no responde. Verifica que el servicio esté corriendo.
    echo  Abri "Servicios" de Windows y asegurate que postgresql este iniciado.
    echo.
    pause
)

:: ── Abrir navegador después de 3 segundos ─────────────
echo  Iniciando servidor...
start /b cmd /c "timeout /t 3 /nobreak >nul && start http://127.0.0.1:5000"

:: ── Arrancar servidor ─────────────────────────────────
echo.
echo  Servidor corriendo en: http://127.0.0.1:5000
echo  Para cerrar el sistema presioná Ctrl+C
echo.
python server.py

:: ── Al cerrar ─────────────────────────────────────────
echo.
echo  Sistema cerrado.
pause
