@echo off
setlocal
cd /d "%~dp0"

if not exist "dist\Typeset Studio\Typeset Studio.exe" goto NOBUILD

rem Find the Inno Setup compiler (ISCC.exe): versions 7 and 6, both roots.
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 7\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC goto NOINNO

echo Building installer with:
echo    %ISCC%
echo.
"%ISCC%" "typeset-studio.iss"
echo.
echo ============================================================
echo  Done. If the compile above succeeded, your installer is:
echo    dist_installer\TypesetStudio-Setup-1.0.0.exe
echo ============================================================
goto END

:NOBUILD
echo.
echo The app has not been built yet.
echo Run build.bat first to create "dist\Typeset Studio\", then run this again.
goto END

:NOINNO
echo.
echo Inno Setup was not found (checked versions 6 and 7).
echo Get it free from https://jrsoftware.org/isdl.php then run this again.
goto END

:END
echo.
pause
