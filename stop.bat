@echo off
setlocal EnableExtensions

echo ============================================
echo   Translatale - Stopping Servers
echo ============================================
echo.

set "STOPPED=0"

:: 1. Kill processes listening on port 8000 (Backend)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do (
    if not "%%P"=="0" (
        echo Menghentikan Backend ^(PID %%P, port 8000^)...
        taskkill /PID %%P /T /F >nul 2>&1
        set "STOPPED=1"
    )
)

:: 2. Kill processes listening on port 5173 (Frontend)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":5173 .*LISTENING"') do (
    if not "%%P"=="0" (
        echo Menghentikan Frontend ^(PID %%P, port 5173^)...
        taskkill /PID %%P /T /F >nul 2>&1
        set "STOPPED=1"
    )
)

:: 3. Close the launcher CMD windows if still open
taskkill /FI "WINDOWTITLE eq Translatale Backend (8000)*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Translatale Frontend (5173)*" /F >nul 2>&1

if "%STOPPED%"=="0" (
    echo Tidak ada server Translatale yang sedang berjalan di port 8000 / 5173.
) else (
    echo.
    echo Semua server Translatale berhasil dihentikan.
)

ping -n 3 127.0.0.1 >nul
endlocal
