@echo off
chcp 65001 >nul
setlocal
set "PORT=8765"

echo ============================================
echo   停止 GGUF Benchmark
echo ============================================
echo.
echo [INFO] 正在停止后端服务（监听端口 %PORT%）...

set "FOUND=0"
for /f "delims=" %%p in ('powershell -NoProfile -Command "(Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue).OwningProcess | Select-Object -Unique"') do (
  echo   - 结束进程 PID %%p
  taskkill /F /T /PID %%p >nul 2>nul
  set "FOUND=1"
)
if "!FOUND!"=="0" echo   - 未发现监听 %PORT% 的进程（可能已停止）。

echo.
echo [OK] 已停止。若仍有残留的 llama-server.exe，可在任务管理器中结束它。
pause
