@echo off
chcp 65001 >nul
cd /d %~dp0

echo 正在停止后端服务（8000 端口）...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)

echo 正在停止 Docker 容器（MySQL / Qdrant / Neo4j）...
docker compose --profile with-mysql down

echo.
echo 已停止。按任意键关闭窗口。
pause
