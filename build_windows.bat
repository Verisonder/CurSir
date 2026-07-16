@echo off
REM ============================================================
REM  Build CurSir into a single standalone Windows .exe.
REM  Run this ON WINDOWS (double-click it). Needs Python once,
REM  to build - the resulting exe needs nothing.
REM ============================================================
echo Building CurSir.exe ...
python -m pip install --upgrade pyinstaller PySide6 pynput
pyinstaller --noconfirm --onefile --windowed --name CurSir cursir.py
echo.
echo ============================================================
echo  Done. Your app is here:   dist\CurSir.exe
echo  That single file needs no Python - share it or run it.
echo ============================================================
pause
