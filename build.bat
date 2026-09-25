@echo off
REM ==========================================
REM   Teacher Day - Build Script
REM   Skips pip install, builds directly.
REM   If you need to install deps, run:
REM     pip install -r requirements.txt
REM     pip install pyinstaller
REM ==========================================

echo ========================================
echo   Teacher Day - Build Script
echo ========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.8+ and add it to PATH.
    pause
    exit /b 1
)

REM Clean previous build artifacts
if exist build rmdir /s /q build
if exist *.spec del /q *.spec

echo [1/1] Building exe (single file, no console window)...
python -m PyInstaller --onefile --noconsole --name "TeacherDay" --add-data "greeting.html;." --add-data "config.json;." teacher_day.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed.
    echo If missing dependencies, run:
    echo   pip install -r requirements.txt
    echo   pip install pyinstaller
    pause
    exit /b 1
)

echo.
echo ========================================
echo   Build complete!
echo   Output: dist\TeacherDay.exe
echo   Put greeting.html and config.json
echo   in the same folder as the exe.
echo ========================================
pause
