@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d %~dp0
title 服装智能客服 - 一键启动

echo ============================================================
echo   基于 LangChain + 知识图谱双引擎的服装多源文档智能客服系统
echo ============================================================
echo.

REM ------------------------------------------------------------
REM 1. 检查 Python 虚拟环境（没有就自动创建并安装依赖）
REM ------------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [1/5] 未发现虚拟环境，正在创建 .venv ...
    py -3.9 -m venv .venv >nul 2>&1
    if not exist ".venv\Scripts\python.exe" (
        py -3 -m venv .venv
    )
    if not exist ".venv\Scripts\python.exe" (
        echo [错误] 创建虚拟环境失败，请先安装 Python 3.9 及以上版本。
        echo        下载地址：https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

echo [1/5] 检查后端依赖 ...
".venv\Scripts\python.exe" -c "import fastapi, langchain_openai, qdrant_client, neo4j, pdfplumber" >nul 2>&1
if errorlevel 1 (
    echo       正在安装后端依赖，首次安装约 5~10 分钟，请耐心等待 ...
    ".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络后重试。
        pause
        exit /b 1
    )
)

REM ------------------------------------------------------------
REM 2. 检查 Docker（Qdrant / Neo4j 依赖 Docker 运行）
REM ------------------------------------------------------------
echo [2/5] 检查 Docker 引擎 ...
set "DOCKER_OK=1"
docker info >nul 2>&1
if errorlevel 1 (
    set "DOCKER_OK=0"
    echo.
    echo [警告] Docker 引擎未就绪，Qdrant 与 Neo4j 将无法启动。
    echo        如果你是第一次使用 Docker，请按下面步骤开启虚拟化后重启电脑：
    echo          1^) 以管理员身份打开 PowerShell，执行：
    echo             dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
    echo             dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
    echo          2^) 执行 wsl --update
    echo          3^) 重启电脑后重新双击 start.bat
    echo.
    echo        仍将尝试启动后端，但问答检索功能会处于降级状态。
    echo.
    pause
    goto :check_mysql
)

echo        Docker 正常，正在启动向量库与图数据库 ...
REM ------------------------------------------------------------
REM 3. 判断本机是否已有 MySQL（有则只启动 qdrant + neo4j）
REM ------------------------------------------------------------
:check_mysql
powershell -NoProfile -Command "if (Test-NetConnection -ComputerName 127.0.0.1 -Port 3306 -InformationLevel Quiet) { exit 0 } else { exit 1 }"
if not errorlevel 1 (
    echo [3/5] 检测到本机 MySQL ^(3306^)，使用本机 MySQL 作为业务库。
    if "!DOCKER_OK!"=="1" docker compose up -d qdrant neo4j
) else (
    echo [3/5] 未检测到本机 MySQL，使用 Docker 启动 MySQL ^(映射到 3307^)。
    if "!DOCKER_OK!"=="1" (
        set "MYSQL_PORT=3307"
        docker compose --profile with-mysql up -d
    )
)
if "!DOCKER_OK!"=="0" echo       Docker 未就绪，已跳过容器启动，检索功能将降级。

REM ------------------------------------------------------------
REM 4. 前端构建产物检查（已构建过则跳过）
REM ------------------------------------------------------------
echo [4/5] 检查前端页面 ...
if not exist "frontend\dist\index.html" (
    echo       正在构建前端页面，请稍候 ...
    pushd frontend
    call npm install
    call npm run build
    popd
    if not exist "frontend\dist\index.html" (
        echo [错误] 前端构建失败，请确认已安装 Node.js 18 及以上版本。
        pause
        exit /b 1
    )
)

REM ------------------------------------------------------------
REM 5. 启动后端服务（默认 8000 端口）
REM ------------------------------------------------------------
echo [5/5] 正在启动后端服务 ...
echo.
echo   管理端： http://127.0.0.1:8000/admin   ^(账号 admin / 密码 123456^)
echo   客户端： http://127.0.0.1:8000/
for /f %%i in ('powershell -NoProfile -Command "(Get-NetIPAddress -AddressFamily IPv4 ^| Where-Object {$_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*'} ^| Select-Object -First 1 -ExpandProperty IPAddress)"') do set "LANIP=%%i"
if defined LANIP echo   手机访问： http://!LANIP!:8000/   （手机与电脑需在同一局域网）
echo.
echo   关闭本窗口即可停止后端服务。
echo ============================================================
echo.

REM 延迟几秒后自动打开管理端页面，方便演示
start "" cmd /c "timeout /t 6 >nul & start http://127.0.0.1:8000/admin"

".venv\Scripts\python.exe" backend\run.py

echo.
echo 服务已停止。按任意键关闭窗口。
pause
