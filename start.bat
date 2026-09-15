@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

set "APP_NAME=GGUF Benchmark"
set "BACKEND_URL=http://127.0.0.1:8765/"

echo ============================================
echo   %APP_NAME% - Strix Halo Test Tool
echo ============================================
echo.

REM ---- 1) 定位 Python ----
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] 未找到 Python。请安装 Python 3.11+ 并勾选 "Add python.exe to PATH"。
  echo         下载: https://www.python.org/downloads/windows/
  pause
  exit /b 1
)

REM ---- 2) 版本检查（需要 ^>= 3.11）----
set "PYVER="
for /f "delims=" %%v in ('python -c "import sys;print(str(sys.version_info[0])+chr(46)+str(sys.version_info[1]))"') do set "PYVER=%%v"
if not defined PYVER (
  echo [ERROR] 无法获取 Python 版本。
  pause
  exit /b 1
)
for /f "tokens=1,2 delims=." %%a in ("!PYVER!") do (
  set "PYMAJ=%%a"
  set "PYMIN=%%b"
)
if !PYMAJ! LSS 3 (
  echo [ERROR] 需要 Python 3.11 或更高版本，当前为 !PYVER!。
  pause
  exit /b 1
)
if !PYMAJ! EQU 3 if !PYMIN! LSS 11 (
  echo [ERROR] 需要 Python 3.11 或更高版本，当前为 !PYVER!。
  pause
  exit /b 1
)
echo [INFO] Python 版本: !PYVER!

REM ---- 3) 虚拟环境 ----
if not exist ".venv\Scripts\python.exe" (
  echo [INFO] 首次运行，正在创建虚拟环境 .venv ...
  python -m venv .venv
  if errorlevel 1 (
    echo [ERROR] 创建虚拟环境失败。
    pause
    exit /b 1
  )
)
set "PYEXE=.venv\Scripts\python.exe"
set "PYW=.venv\Scripts\pythonw.exe"
if not exist "!PYW!" set "PYW=!PYEXE!"

REM ---- 4) 安装依赖 ----
echo [INFO] 检查依赖（首次较慢，请耐心等待）...
"!PYEXE!" -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo [WARN] 依赖安装可能未完全成功；若界面功能异常，请检查网络后重新运行本脚本。
)

REM ---- 5) 后台启动后端 ----
REM 用 pythonw.exe（GUI 子系统，无控制台窗口）配合 start（不加 /B），
REM 使后端进程与当前控制台解耦 —— 关闭本窗口不会中断服务。
echo [INFO] 后台启动后端服务 ...
start "%APP_NAME% Backend" "!PYW!" run.py

REM ---- 6) 等待后端就绪（最多约 15 次探测）----
set "READY=0"
for /L %%i in (1,1,15) do (
  if "!READY!"=="0" (
    set "CODE="
    for /f "delims=" %%s in ('powershell -NoProfile -Command "try{(Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 %BACKEND_URL%api/health).StatusCode}catch{0}"') do set "CODE=%%s"
    if "!CODE!"=="200" set "READY=1"
    if "!READY!"=="0" timeout /t 1 /nobreak >nul
  )
)

REM ---- 7) 打开浏览器 ----
if "!READY!"=="1" (
  echo [OK] 后端已就绪，正在打开浏览器 ...
) else (
  echo [WARN] 后端未在预期时间内就绪，仍尝试打开浏览器。
  echo        请查看日志: reports\task.log
)
start "" "%BACKEND_URL%"

echo.
echo [OK] 完成。关闭本窗口不会中断后台服务。
echo      停止服务请运行 stop.bat
endlocal
