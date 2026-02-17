@echo off
echo.
echo  JA . ERP - Sistema de Gestion Completo
echo  ========================================
echo.
echo  Verificando dependencias...
pip install flask reportlab -q
echo.
echo  Iniciando servidor local...
start "" http://localhost:5000
python app.py
pause
