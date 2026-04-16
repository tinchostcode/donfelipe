@echo off
set DATABASE_URL=postgresql://postgres:domi.kero@localhost:5432/donfelipe
set SECRET_KEY=donfelipe-local-2026
set GEMINI_API_KEY=AIzaSyAvecKaFJXLfCx4xz9B04ocA1D-vnb6bjA
echo Iniciando Don Felipe...
python server.py
pause