@echo off
echo ==========================================
echo      MOLODOY BOT - PUBLICADOR AUTOMATICO
echo ==========================================

:: 0. Ler versao do version.txt e atualizar auto_update.py
echo [0/3] Atualizando versao no codigo...
set /p VERSION=<version.txt
echo Versao: %VERSION%

:: Atualiza CURRENT_VERSION no auto_update.py usando PowerShell
powershell -Command "(Get-Content 'auto_update.py') -replace 'CURRENT_VERSION = \"[^\"]+\"', 'CURRENT_VERSION = \"%VERSION%\"' | Set-Content 'auto_update.py'"
if %errorlevel% neq 0 (
    echo ERRO: Falha ao atualizar versao no auto_update.py!
    pause
    exit /b
)
echo Versao %VERSION% injetada no auto_update.py

:: 1. Compilar o Bot
echo [1/3] Compilando o .exe...
pyinstaller MolodoyBot.spec
if %errorlevel% neq 0 (
    echo ERRO: Falha na compilacao!
    pause
    exit /b
)

:: 2. Limpar Release Antiga (Tag 'latest')
echo [2/3] Removendo release 'latest' antiga...
gh release delete latest --cleanup-tag --yes
:: Nota: O comando acima deleta a release e a tag para recriarmos do zero

:: 3. Criar Nova Release e Upar o Arquivo
echo [3/3] Enviando para o GitHub...
gh release create latest dist/MolodoyBot.exe --title "Latest Version" --notes "Atualizacao automatica via VS Code"

echo.
echo ==========================================
echo      SUCESSO! NOVA VERSAO DISPONIVEL
echo      Versao publicada: %VERSION%
echo ==========================================
pause
