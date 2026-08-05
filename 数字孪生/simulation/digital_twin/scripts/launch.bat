@echo off
echo ============================================
echo   STM32 Digital Twin - Launcher
echo ============================================
echo.
echo Select mode:
echo   [1] 2D Simulator
echo   [2] 3D Perspective Simulator
echo   [3] 3D Scan Pipeline
echo   [4] PPO Training
echo   [5] Run Tests
echo.
set /p choice="Enter choice (1-5): "

if "%choice%"=="1" (
    echo Starting 2D simulator...
    python main.py
) else if "%choice%"=="2" (
    echo Starting 3D simulator...
    python main_3d.py
) else if "%choice%"=="3" (
    echo Starting 3D scan pipeline...
    python main_scan.py --demo
) else if "%choice%"=="4" (
    echo Starting PPO training...
    python train_ppo.py
) else if "%choice%"=="5" (
    echo Running tests...
    python -m pytest tests/ -v
) else (
    echo Invalid choice
)
pause
