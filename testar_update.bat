@echo off
echo ==========================================
echo      TESTE LOCAL DO AUTO-UPDATE
echo ==========================================

:: Cria pasta de teste
set TESTDIR=_teste_update
if exist %TESTDIR% rmdir /s /q %TESTDIR%
mkdir %TESTDIR%

:: Compila o bot
echo [1/4] Compilando o bot...
pyinstaller MolodoyBot.spec
if %errorlevel% neq 0 (
    echo ERRO: Falha na compilacao!
    pause
    exit /b
)

:: Copia o exe para pasta de teste
echo [2/4] Preparando ambiente de teste...
copy dist\MolodoyBot.exe %TESTDIR%\

:: Cria arquivos legados falsos
echo 5.0 > %TESTDIR%\version.txt
echo fake > %TESTDIR%\MolodoyLauncher.exe

echo.
echo [3/4] Arquivos na pasta de teste ANTES:
dir %TESTDIR% /b

echo.
echo [4/4] Executando o bot...
echo (O bot vai abrir - feche-o manualmente apos verificar)
echo.
start "" /wait %TESTDIR%\MolodoyBot.exe

echo.
echo Arquivos na pasta de teste DEPOIS:
dir %TESTDIR% /b

echo.
echo ==========================================
echo Se MolodoyLauncher.exe e version.txt
echo sumiram, o cleanup funcionou!
echo ==========================================
pause
