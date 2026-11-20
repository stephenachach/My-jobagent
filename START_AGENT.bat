@echo off
title Job Agent
cd /d "%~dp0"
echo ==================================================
echo   JOB AGENT - starting...
echo   Keep this window OPEN or minimized.
echo   Close it to stop the agent.
echo ==================================================
echo.

where python >nul 2>nul
if %errorlevel%==0 goto :runpython

where py >nul 2>nul
if %errorlevel%==0 goto :runpy

echo [!] PYTHON NOT FOUND on this computer.
echo.
echo     1. Download it free from:  https://www.python.org/downloads/
echo     2. Run the installer
echo     3. IMPORTANT: tick the box  "Add Python to PATH"  on the first screen
echo     4. When it finishes, double-click this file again.
echo.
pause
exit /b

:runpython
python "%~dp0start.py"
goto :end

:runpy
py -3 "%~dp0start.py"
goto :end

:end
echo.
echo Agent stopped. (If this closed unexpectedly, take a screenshot and read the error above.)
echo The dashboard is at http://127.0.0.1:7860 - keep this window open.
pause
