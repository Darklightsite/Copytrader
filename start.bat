@echo off
title Trade Masolo Watchdog

REM A 'call' paranccsal inditjuk a masik szkriptet.
REM Ez garantalja, hogy a vegen visszater a vezerles.
call upload.cmd

:start
echo.
echo ===================================================
echo Trade Masolo inditasa (%date% %time%)
echo ===================================================
echo.
py copyer.py

echo.
echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
echo !!! A masolo program leallt vagy hibat dobott! !!!
echo !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
echo.
echo Ujrainditas 10 masodperc mulva...
timeout /t 10 /nobreak

goto start