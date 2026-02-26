@echo off
echo ==========================================
echo      MOLODOY BOT - PUBLICADOR AUTOMATICO
echo ==========================================

:: Python 32-bit (necessario para o bot funcionar com Tibia 32-bit)
set PYTHON32=C:\Users\vitor\AppData\Local\Programs\Python\Python313-32\python.exe

:: 0. Ler versao do version.txt e atualizar auto_update.py
echo [0/3] Atualizando versao no codigo...
set /p VERSION=<version.txt
echo Versao: %VERSION%

:: Atualiza CURRENT_VERSION no auto_update.py (feito automaticamente pelo spec)
:: %PYTHON32% update_version.py

:: Gera splash.png com a versao
%PYTHON32% generate_splash.py
if %errorlevel% neq 0 (
    echo ERRO: Falha ao gerar splash.png!
    pause
    exit /b
)

:: 1. Compilar o Bot
echo [1/3] Compilando o .exe...
%PYTHON32% -m PyInstaller MolodoyBot.spec --noconfirm
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
