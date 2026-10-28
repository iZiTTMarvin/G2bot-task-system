@echo off
rem G2 任务系统本地启动入口（Windows）
rem 用法：
rem   start.bat            正式模式：需要真实模型配置（设置页填写）
rem   start.bat demo       演示模式：无凭据，用确定性 FakeModel 走通全流程
rem   start.bat dev        开发模式：前端 Vite 热重载（5173）+ 后端（8000）
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set MODE=%1
if "%MODE%"=="" set MODE=run

if not exist backend\.venv\Scripts\python.exe (
  echo [1/3] 创建 Python 虚拟环境并安装依赖...
  python -m venv backend\.venv || goto :error
  backend\.venv\Scripts\python -m pip install --upgrade pip -q || goto :error
  backend\.venv\Scripts\pip install -r backend\requirements.txt -q || goto :error
)

if not exist frontend\node_modules (
  echo [2/3] 安装前端依赖...
  cd frontend
  call npm install || goto :error
  cd ..
)

if not exist frontend\dist (
  echo [3/3] 构建前端...
  cd frontend
  call npm run build || goto :error
  cd ..
)

if "%MODE%"=="dev" (
  echo 开发模式：后端 http://127.0.0.1:8000 ，前端 http://127.0.0.1:5173
  start "G2-backend" cmd /c "cd /d %~dp0backend && .venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
  cd frontend
  call npm run dev
  goto :end
)

if "%MODE%"=="demo" (
  echo 演示模式（无凭据 FakeModel）：http://127.0.0.1:8000
  set G2_DEMO_FAKE_MODEL=1
  cd backend
  .venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
  goto :end
)

echo 正式模式（真实模型）：http://127.0.0.1:8000  先在「设置」页配置模型与密钥
cd backend
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto :end

:error
echo 启动失败，请检查上方错误信息。
exit /b 1

:end
endlocal
