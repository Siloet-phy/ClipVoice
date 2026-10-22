@echo off
chcp 65001 >nul 2>&1
echo ========================================
echo   ClipVoice - 智能剪切板管理器
echo ========================================
echo.

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.8+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM 检查依赖
python -c "import ttkbootstrap, PIL, sounddevice, soundfile, win32clipboard" >nul 2>&1
if errorlevel 1 (
    echo [提示] 首次运行，正在安装依赖...
    pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo [错误] 依赖安装失败
        pause
        exit /b 1
    )
)

echo 正在启动 ClipVoice...
echo.
python src\clipboard_manager.py

if errorlevel 1 (
    echo.
    echo [错误] 程序运行出错
    pause
)
