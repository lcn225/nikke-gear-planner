@echo off
chcp 936 >nul
title NIKKE Gear Planner

echo =======================================
echo   NIKKE 装备优化规划器 - GUI
echo =======================================
echo.
echo 正在启动 Streamlit 服务器...
echo.

cd /d "%~dp0"
python -m streamlit run app.py

pause
