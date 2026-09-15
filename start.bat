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

REM =====================================================================
REM  Python 发现（重要）
REM
REM  `where python` 命中并不代表存在可用的解释器：Windows 10/11 自带
REM  Microsoft Store 的「应用执行别名」
REM    %LOCALAPPDATA%\Microsoft\WindowsApps\python.exe / python3.exe
REM  它是 0 字节占位程序，被调用时只会打印一行英文提示并退出，
REM  而 WindowsApps 默认在 PATH 中且优先级常高于真实安装。
REM
REM  因此本脚本对每个候选都「实际执行 + 校验输出是否为版本号」，
REM  并且主动跳过 WindowsApps 下的路径（避免误触发 Microsoft Store）。
REM =====================================================================
set "PY_EXE="
set "PY_VER="
set "STORE_ALIAS=0"

REM 记录是否存在商店别名，用于给出针对性提示
for /f "delims=" %%p in ('where python 2^>nul ^| findstr /i /c:"WindowsApps"') do set "STORE_ALIAS=1"
for /f "delims=" %%p in ('where python3 2^>nul ^| findstr /i /c:"WindowsApps"') do set "STORE_ALIAS=1"

REM 1) py 启动器：随 Python 安装写入 C:\Windows\，不会被商店别名遮蔽
call :try_cmd "py -3"
call :try_cmd "py"

REM 2) PATH 中真实存在的 python / python3（逐条按完整路径探测，跳过 WindowsApps）
for /f "delims=" %%p in ('where python 2^>nul') do (
  echo %%~fp| findstr /i /c:"WindowsApps" >nul 2>nul
  if errorlevel 1 call :try_exe "%%~fp"
)
for /f "delims=" %%p in ('where python3 2^>nul') do (
  echo %%~fp| findstr /i /c:"WindowsApps" >nul 2>nul
  if errorlevel 1 call :try_exe "%%~fp"
)

REM 3) 兜底：扫描常见安装目录（绕过 PATH 配置问题）
call :scan_dirs

if not defined PY_EXE (
  echo [ERROR] 未能找到可用的 Python 解释器。
  echo.
  if "!STORE_ALIAS!"=="1" (
    echo   已检测到 Microsoft Store 的 python.exe「应用执行别名」。
    echo   它只是一个占位程序，不是真正的 Python：被调用时会打印一行英文提示
    echo   ^(Python was not found ... Microsoft Store^) 后直接退出。
  )
  echo   请任选一种方式修复：
  echo.
  echo   [方式 A] 安装 Python 3.11+（推荐，一步到位）
  echo     1. 打开 https://www.python.org/downloads/windows/
  echo     2. 下载 Windows installer，64-bit 版本
  echo     3. 安装第一屏务必勾选 "Add python.exe to PATH"
  echo     4. 安装完成后重新运行本脚本
  echo.
  echo   [方式 B] 已装 Python，但被商店别名遮蔽（此时 py 通常仍可用）
  echo     关闭别名：设置 - 应用 - 高级应用设置 - 应用执行别名
  echo     把 "python.exe" 与 "python3.exe" 两个开关都关掉，再重新运行本脚本
  echo.
  echo   [方式 C] 先自检：在「终端」里执行  py -3 --version
  echo     能看到版本号说明 Python 已安装，属于方式 B 的情况
  echo.
  pause
  exit /b 1
)

echo [INFO] Python 解释器: !PY_EXE!
echo [INFO] Python 版本  : !PY_VER!

REM ---- 版本检查（需要 ^>= 3.11）----
for /f "tokens=1,2 delims=." %%a in ("!PY_VER!") do (
  set "PYMAJ=%%a"
  set "PYMIN=%%b"
)
set "VER_OK=1"
if !PYMAJ! LSS 3 set "VER_OK=0"
if !PYMAJ! EQU 3 if !PYMIN! LSS 11 set "VER_OK=0"
if "!VER_OK!"=="0" (
  echo [ERROR] 需要 Python 3.11 或更高版本，当前为 !PY_VER!。
  echo         下载: https://www.python.org/downloads/windows/
  echo         提示: 多版本共存时可用 py -3.12 之类指定版本。
  pause
  exit /b 1
)

REM ---- 虚拟环境 ----
if not exist ".venv\Scripts\python.exe" (
  echo [INFO] 首次运行，正在创建虚拟环境 .venv ...
  "!PY_EXE!" -m venv .venv
  if errorlevel 1 (
    echo [ERROR] 创建虚拟环境失败。
    pause
    exit /b 1
  )
)
set "PYEXE=.venv\Scripts\python.exe"
set "PYW=.venv\Scripts\pythonw.exe"
if not exist "!PYW!" set "PYW=!PYEXE!"

REM ---- 安装依赖 ----
echo [INFO] 检查依赖（首次较慢，请耐心等待）...
"!PYEXE!" -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo [WARN] 依赖安装可能未完全成功；若界面功能异常，请检查网络后重新运行本脚本。
)

REM ---- 后台启动后端 ----
REM 用 pythonw.exe（GUI 子系统，无控制台窗口）配合 start（不加 /B），
REM 使后端进程与当前控制台解耦 —— 关闭本窗口不会中断服务。
echo [INFO] 后台启动后端服务 ...
start "%APP_NAME% Backend" "!PYW!" run.py

REM ---- 等待后端就绪（最多约 15 次探测）----
set "READY=0"
for /L %%i in (1,1,15) do (
  if "!READY!"=="0" (
    set "CODE="
    for /f "delims=" %%s in ('powershell -NoProfile -Command "try{(Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 %BACKEND_URL%api/health).StatusCode}catch{0}"') do set "CODE=%%s"
    if "!CODE!"=="200" set "READY=1"
    if "!READY!"=="0" timeout /t 1 /nobreak >nul
  )
)

REM ---- 打开浏览器 ----
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
exit /b 0

REM =====================================================================
REM  子过程
REM =====================================================================

REM :probe <候选命令>  —— 实际执行候选解释器并校验输出
REM 只有输出严格形如 "3.11" 才视为有效（商店别名输出为空，会被判为无效）
:probe
set "PROBE_VER="
set "PROBE_EXE="
for /f "delims=" %%o in ('%~1 -c "import sys;print(str(sys.version_info[0])+chr(46)+str(sys.version_info[1]))" 2^>nul') do set "PROBE_VER=%%o"
if not defined PROBE_VER exit /b 0
echo !PROBE_VER!| findstr /r /c:"^[0-9][0-9]*\.[0-9][0-9]*$" >nul 2>nul
if errorlevel 1 (
  set "PROBE_VER="
  exit /b 0
)
for /f "delims=" %%o in ('%~1 -c "import sys;print(sys.executable)" 2^>nul') do set "PROBE_EXE=%%o"
if not defined PROBE_EXE set "PROBE_VER="
exit /b 0

REM :try_cmd <命令字符串>  —— 命令式候选（如 "py -3"）
:try_cmd
if defined PY_EXE exit /b 0
call :probe "%~1"
if defined PROBE_VER (
  set "PY_EXE=!PROBE_EXE!"
  set "PY_VER=!PROBE_VER!"
)
exit /b 0

REM :try_exe <可执行文件完整路径>  —— 路径式候选
:try_exe
if defined PY_EXE exit /b 0
call :probe ""%~1""
if defined PROBE_VER (
  set "PY_EXE=!PROBE_EXE!"
  set "PY_VER=!PROBE_VER!"
)
exit /b 0

REM :scan_dirs —— 扫描常见安装目录
:scan_dirs
if defined PY_EXE exit /b 0
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
  if exist "%%~fD\python.exe" call :try_exe "%%~fD\python.exe"
)
if defined PY_EXE exit /b 0
for /d %%D in ("%ProgramFiles%\Python3*") do (
  if exist "%%~fD\python.exe" call :try_exe "%%~fD\python.exe"
)
if defined PY_EXE exit /b 0
for /d %%D in ("C:\Python3*") do (
  if exist "%%~fD\python.exe" call :try_exe "%%~fD\python.exe"
)
exit /b 0
