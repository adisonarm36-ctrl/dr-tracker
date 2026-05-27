@echo off
title DR Tracker Orchestrator
echo [1/3] Installing/Checking Dependencies...
pip install fastapi uvicorn yfinance pytz
echo [2/3] Starting Backend Server...
start /b python backend/main.py
echo [3/3] Launching Dashboard...
timeout /t 5
start index.html
echo System Active.
