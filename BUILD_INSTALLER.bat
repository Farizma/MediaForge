@echo off
setlocal
cd /d "%~dp0"
title MediaForge - build the setup wizard
echo.
echo  ==============================================
echo    MediaForge - build MediaForge_setup_vX.Y.Z.exe
echo  ==============================================
echo.

call :find_iscc
if defined ISCC goto :have_iscc

echo  Inno Setup 6 was not found. It turns the program into a normal Windows
echo  setup wizard, and is only needed to BUILD the installer.
echo.
choice /C YN /M " Install Inno Setup 6 now (uses winget)"
if errorlevel 2 goto :no_iscc
winget install -e --id JRSoftware.InnoSetup --accept-package-agreements --accept-source-agreements
call :find_iscc
if defined ISCC goto :have_iscc
echo.
echo  Inno Setup was installed, but this window cannot see it yet.
echo  Please CLOSE this window and double-click BUILD_INSTALLER.bat again.
echo.
pause
exit /b

:no_iscc
echo.
echo  Please install Inno Setup 6 from https://jrsoftware.org/isdl.php,
echo  then double-click BUILD_INSTALLER.bat again.
echo.
pause
exit /b

:have_iscc
echo  Using Inno Setup: %ISCC%
rem BUILD_EXE.bat finds (or offers to install) Python, builds the program, then the installer.
call "%~dp0BUILD_EXE.bat" --installer %*
exit /b

:find_iscc
set "ISCC="
for %%P in ("%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe") do (
  if not defined ISCC if exist %%P set "ISCC=%%~P"
)
if not defined ISCC (
  for /f "usebackq delims=" %%I in (`where iscc 2^>nul`) do if not defined ISCC set "ISCC=%%I"
)
exit /b 0
