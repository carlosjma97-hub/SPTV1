@echo off
chcp 65001 >nul
cd /d "%~dp0"
if "%ANTHROPIC_API_KEY%"=="" set /p ANTHROPIC_API_KEY=Pega tu API key de Anthropic: 
python -m pip install -r requirements.txt -q
python clippy_cyberpunk.py
pause
