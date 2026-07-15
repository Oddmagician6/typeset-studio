@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\activate.bat" goto NOVENV

call ".venv\Scripts\activate.bat"
echo Installing build tools...
pip install -r requirements-build.txt

echo.
echo Building Typeset Studio (this takes a few minutes)...
pyinstaller typeset-studio.spec --noconfirm --clean

echo.
echo ============================================================
echo  Build complete.
echo  App folder: dist\Typeset Studio\
echo  Run it:     dist\Typeset Studio\Typeset Studio.exe
echo ============================================================
goto END

:NOVENV
echo.
echo No .venv found. Run run.bat once first to create the workspace,
echo then run build.bat again.

:END
echo.
pause
