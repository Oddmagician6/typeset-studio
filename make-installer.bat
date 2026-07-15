@echo off
setlocal
cd /d "%~dp0"

if not exist "dist\Typeset Studio\Typeset Studio.exe" (
  echo.
  echo The app has not been built yet.
  echo Run build.bat first to create dist\Typeset Studio\, then re-run make-installer.bat.
  echo.
  pause
  exit /b 1
)

rem Find the Inno Setup compiler (ISCC.exe): versions 7 and 6, both Program
rem Files roots. Flat "if" lines on purpose — a for-loop would choke on the
rem parentheses inside the ProgramFiles(x86) path.
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 7\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"

if not defined ISCC (
  echo.
  echo Inno Setup was not found (looked for versions 6 and 7).
  echo Install it (free) from https://jrsoftware.org/isdl.php then re-run this file.
  echo.
  pause
  exit /b 1
)

echo Building installer with "%ISCC%" ...
"%ISCC%" "typeset-studio.iss"

echo.
echo ============================================================
echo  Installer built:  dist_installer\TypesetStudio-Setup-1.0.0.exe
echo ============================================================
pause
