@echo off
echo ==========================================
echo      MOLODOY BOT - PUBLICADOR AUTOMATICO
echo ==========================================

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
echo ==========================================
pause