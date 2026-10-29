@echo off
rem G2 task system launcher (Windows)
rem Usage:
rem   start.bat            run mode: real model required (configure on Settings page)
rem   start.bat demo       demo mode: deterministic FakeModel, no credentials needed
rem   start.bat dev        dev mode: frontend Vite hot reload (5173) + backend (8000)
rem NOTE: keep this file ASCII-only. cmd.exe parses .bat with the console
rem codepage; non-ASCII bytes plus a mid-file "chcp" make cmd mis-seek and
rem execute line fragments as commands (verified on zh-CN Windows, cp936).
setlocal
cd /d "%~dp0"

set MODE=%1
if "%MODE%"=="" set MODE=run

if not exist backend\.venv\Scripts\python.exe (
  echo [1/3] Creating Python venv and installing dependencies...
  python -m venv backend\.venv || goto :error
  backend\.venv\Scripts\python -m pip install --upgrade pip -q || goto :error
  backend\.venv\Scripts\pip install -r backend\requirements.txt -q || goto :error
)

if not exist frontend\node_modules (
  echo [2/3] Installing frontend dependencies...
  cd frontend
  call npm install || goto :error
  cd ..
)

if not exist frontend\dist (
  echo [3/3] Building frontend...
  cd frontend
  call npm run build || goto :error
  cd ..
)

if "%MODE%"=="dev" (
  echo Dev mode: backend http://127.0.0.1:8000 , frontend http://127.0.0.1:5173
  start "G2-backend" cmd /c "cd /d %~dp0backend && .venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
  cd frontend
  call npm run dev
  goto :end
)

if "%MODE%"=="demo" (
  echo Demo mode - FakeModel, no credentials: http://127.0.0.1:8000
  set G2_DEMO_FAKE_MODEL=1
  cd backend
  .venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
  goto :end
)

echo Run mode - real model: http://127.0.0.1:8000  - configure model and API key on the Settings page first
cd backend
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto :end

:error
echo Startup failed. Check the error messages above.
exit /b 1

:end
endlocal
