@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"
title Translatale (BE + FE)

echo ============================================
echo   Translatale - Setup ^& Launcher
echo ============================================
echo.

:: 1. Check Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python tidak ditemukan di PATH.
    echo Silakan install Python 3.10+ terlebih dahulu.
    pause
    exit /b 1
)

:: 2. Check Node.js / npm
where npm.cmd >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js / npm tidak ditemukan di PATH.
    echo Silakan install Node.js 18+ terlebih dahulu.
    pause
    exit /b 1
)

:: 3. Backend venv & dependencies (first run or requirements.txt changed)
if not exist "%ROOT_DIR%backend\.venv\Scripts\python.exe" (
    echo [1/4] Membuat Python virtual environment di backend\.venv ...
    python -m venv "%ROOT_DIR%backend\.venv"
    if errorlevel 1 (
        echo [ERROR] Gagal membuat virtual environment.
        pause
        exit /b 1
    )
)

set "NEED_PIP=0"
if not exist "%ROOT_DIR%backend\.venv\.requirements.installed" (
    set "NEED_PIP=1"
) else (
    fc /b "%ROOT_DIR%backend\requirements.txt" "%ROOT_DIR%backend\.venv\.requirements.installed" >nul 2>&1
    if errorlevel 1 set "NEED_PIP=1"
)

if "%NEED_PIP%"=="1" (
    echo [2/4] Menginstall dependensi backend ^(requirements.txt^)...
    "%ROOT_DIR%backend\.venv\Scripts\python.exe" -m pip install --upgrade pip
    "%ROOT_DIR%backend\.venv\Scripts\python.exe" -m pip install -r "%ROOT_DIR%backend\requirements.txt"
    if errorlevel 1 (
        echo [ERROR] Gagal menginstall dependensi backend.
        pause
        exit /b 1
    )
    copy /y "%ROOT_DIR%backend\requirements.txt" "%ROOT_DIR%backend\.venv\.requirements.installed" >nul
) else (
    echo [2/4] Dependensi backend sudah siap.
)

:: 4. Frontend node_modules (first run or package.json changed)
set "NEED_NPM=0"
if not exist "%ROOT_DIR%frontend\node_modules" (
    set "NEED_NPM=1"
) else if not exist "%ROOT_DIR%frontend\node_modules\.package.installed" (
    set "NEED_NPM=1"
) else (
    fc /b "%ROOT_DIR%frontend\package.json" "%ROOT_DIR%frontend\node_modules\.package.installed" >nul 2>&1
    if errorlevel 1 set "NEED_NPM=1"
)

if "%NEED_NPM%"=="1" (
    echo [3/4] Menginstall dependensi frontend ^(npm install^)...
    pushd "%ROOT_DIR%frontend"
    call npm.cmd install
    if errorlevel 1 (
        popd
        echo [ERROR] Gagal menginstall dependensi frontend.
        pause
        exit /b 1
    )
    popd
    copy /y "%ROOT_DIR%frontend\package.json" "%ROOT_DIR%frontend\node_modules\.package.installed" >nul
) else (
    echo [3/4] Dependensi frontend sudah siap.
)

:: 5. Run single-window launcher (BE + FE with [BE] / [FE] prefixes)
echo [4/4] Menjalankan Backend ^& Frontend dalam 1 window...
echo.
"%ROOT_DIR%backend\.venv\Scripts\python.exe" "%ROOT_DIR%launcher.py"

endlocal
