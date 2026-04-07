@echo off
setlocal

REM Get the directory this .bat lives in (project root)
set "ROOT=%~dp0"

echo ========================================
echo        IRIS v2 - Starting Platform
echo ========================================

REM Ensure directories exist
if not exist "%ROOT%student_db" mkdir "%ROOT%student_db"
if not exist "%ROOT%prof_db" mkdir "%ROOT%prof_db"
if not exist "%ROOT%exam_db" mkdir "%ROOT%exam_db"
if not exist "%ROOT%static" mkdir "%ROOT%static"

REM Init DB using venv python
"%ROOT%venv\Scripts\python.exe" -c "import sys; sys.path.insert(0,r'%ROOT%.'); from sqlmodel import SQLModel; from models import *; from sqlmodel import create_engine; engine=create_engine('sqlite:///./main_app.db'); SQLModel.metadata.create_all(engine); print('DB initialized OK')"
if %errorlevel% neq 0 (
    echo [ERROR] DB initialization failed. Is venv installed?
    pause
    exit /b 1
)

echo.
echo Starting services...

REM Start AI Engine (port 8001)
start "IRIS AI Engine (8001)" cmd /k "cd /d "%ROOT%" && "%ROOT%venv\Scripts\uvicorn.exe" 2_gpu_server:app --host 0.0.0.0 --port 8001"
timeout /t 2 >nul

REM Start Student App (port 8002)
start "IRIS Student App (8002)" cmd /k "cd /d "%ROOT%" && "%ROOT%venv\Scripts\uvicorn.exe" 3_student_app:app --host 0.0.0.0 --port 8002"
timeout /t 1 >nul

echo.
echo -----------------------------------------
echo  AI Engine      : http://localhost:8001
echo  Student App    : http://localhost:8002
echo  Prof Dashboard : http://localhost:8000
echo -----------------------------------------
echo.
echo  Starting Prof Dashboard (port 8000)...
echo  Press Ctrl+C to stop.
echo.

cd /d "%ROOT%"
"%ROOT%venv\Scripts\uvicorn.exe" 1_prof_dash:app --host 0.0.0.0 --port 8000 --reload

endlocal
