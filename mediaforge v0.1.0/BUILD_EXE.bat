@echo off
setlocal
cd /d "%~dp0"
title MediaForge - build the Windows EXE
echo.
echo  ==============================================
echo    MediaForge - build the Windows program
echo  ==============================================
echo.

call :find_python
if defined PY goto :have_python

echo  Python 3.10 or newer was not found on this PC.
echo  It is only needed to BUILD the program.
echo.
choice /C YN /M " Install Python 3.12 now (uses winget, no administrator needed)"
if errorlevel 2 goto :no_python
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
call :find_python
if defined PY goto :have_python
echo.
echo  Python was installed, but this window cannot see it yet.
echo  Please CLOSE this window and double-click BUILD_EXE.bat again.
goto :finish

:no_python
echo.
echo  Please install Python 3.12 from https://www.python.org/downloads/
echo  (tick "Add python.exe to PATH"), then double-click BUILD_EXE.bat again.
goto :finish

:have_python
echo  Using Python: %PY%
echo.
"%PY%" "%~dp0tools\build_exe.py" %*
if errorlevel 1 (
  echo.
  echo  *** The build failed - please read the messages above. ***
)
goto :finish

:finish
echo.
pause
exit /b

:find_python
set "PY="
for %%C in ("py -3" "python") do (
  if not defined PY (
    for /f "usebackq delims=" %%I in (`%%~C -c "import sys; sys.version_info>=(3,10) and print(sys.executable)" 2^>nul`) do set "PY=%%I"
  )
)
if not defined PY (
  for %%P in ("%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" "%LOCALAPPDATA%\Programs\Python\Python310\python.exe") do (
    if not defined PY if exist %%P set "PY=%%~P"
  )
)
exit /b 0
