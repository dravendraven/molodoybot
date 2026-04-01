@echo off
echo ==========================================
echo      MOLODOY BOT - PUBLICADOR AUTOMATICO
echo ==========================================

:: Python 32-bit (necessario para o bot funcionar com Tibia 32-bit)
set PYTHON32=C:\Users\vitor\AppData\Local\Programs\Python\Python313-32\python.exe

:: 0. Ler versao do version.txt e atualizar auto_update.py
echo [0/4] Atualizando versao no codigo...
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

:: 1. Gerar changelog com commits desde ultima versao
echo [1/4] Gerando changelog...
for /f "delims=" %%i in ('git describe --tags --abbrev=0 2^>nul') do set LAST_TAG=%%i
if "%LAST_TAG%"=="" (
    echo Nenhuma tag encontrada, usando ultimos 10 commits
    git log --oneline --no-merges -10 > changelog.txt
) else (
    echo Commits desde %LAST_TAG%:
    git log --oneline --no-merges %LAST_TAG%..HEAD > changelog.txt
)

:: 2. Compilar o Bot
echo [2/4] Compilando o .exe...
%PYTHON32% -m PyInstaller MolodoyBot.spec --noconfirm
if %errorlevel% neq 0 (
    echo ERRO: Falha na compilacao!
    pause
    exit /b
)

:: 3. Limpar Release Antiga (Tag 'latest')
echo [3/4] Removendo release 'latest' antiga...
gh release delete latest --cleanup-tag --yes
:: Nota: O comando acima deleta a release e a tag para recriarmos do zero

:: 4. Criar Nova Release e Upar o Arquivo (com changelog)
echo [4/4] Enviando para o GitHub...
gh release create latest dist/MolodoyBot.exe changelog.txt --title "Latest Version" --notes "Versao %VERSION%"

echo.
echo ==========================================
echo      SUCESSO! NOVA VERSAO DISPONIVEL
echo      Versao publicada: %VERSION%
echo ==========================================
pause
