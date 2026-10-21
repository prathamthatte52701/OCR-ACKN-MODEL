@echo off
setlocal
set "ROOT=%~dp0"
set "RUN=%ROOT%.run"
set "RC=0"
set "PY=%ROOT%venv\Scripts\python.exe"

if not exist "%PY%" (
  echo ERROR: venv missing. Run setup.bat first.
  set "RC=1"
  goto done
)
if not exist "%ROOT%backend\.env" (
  echo ERROR: backend\.env missing. Run setup.bat first.
  set "RC=1"
  goto done
)
set "SZ=0"
for %%F in ("%ROOT%backend\.env") do set "SZ=%%~zF"
if "%SZ%"=="0" (
  echo ERROR: backend\.env is empty. Fill it in, then run setup.bat.
  set "RC=1"
  goto done
)
if not exist "%ROOT%frontend\dist\index.html" (
  echo ERROR: frontend is not built. Run setup.bat first.
  set "RC=1"
  goto done
)
if not exist "%ROOT%admin\dist\index.html" (
  echo ERROR: admin is not built. Run setup.bat first.
  set "RC=1"
  goto done
)
if not exist "%ROOT%frontend\node_modules\vite\bin\vite.js" (
  echo ERROR: frontend packages missing. Run setup.bat first.
  set "RC=1"
  goto done
)
if not exist "%ROOT%admin\node_modules\vite\bin\vite.js" (
  echo ERROR: admin packages missing. Run setup.bat first.
  set "RC=1"
  goto done
)
set "NODE="
for /f "delims=" %%n in ('where node 2^>nul') do if not defined NODE set "NODE=%%n"
if not defined NODE (
  echo ERROR: Node.js not found on PATH. Run setup.bat for details.
  set "RC=1"
  goto done
)

set "LIVE=0"
set "UP=0"
set "BUSY="
call :probe backend 8000 "ACKN Backend"
call :probe user 5174 "ACKN User App"
call :probe admin 5175 "ACKN Admin App"

if "%UP%"=="3" (
  echo Already running.
  goto urls
)
if not "%LIVE%"=="0" (
  echo ERROR: the app is only partly running. Run stop.bat, then start.bat again.
  set "RC=1"
  goto done
)
if defined BUSY (
  echo ERROR: port%BUSY% already in use by another program. Nothing was started.
  set "RC=1"
  goto done
)

if not exist "%RUN%" mkdir "%RUN%"

rem Each app runs in its own minimized, titled cmd window (start "TITLE" /min). The PID recorded
rem in .run is that window's cmd.exe; stop.bat kills its whole tree. No PowerShell here: on some
rem PCs it needs 20 seconds just to start.
start "ACKN Backend" /min /d "%ROOT%backend" cmd /s /c ""%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
call :recordpid backend "ACKN Backend"
if errorlevel 1 goto launchfail
start "ACKN User App" /min /d "%ROOT%frontend" cmd /s /c ""%NODE%" "%ROOT%frontend\node_modules\vite\bin\vite.js" preview --port 5174 --strictPort --host 127.0.0.1"
call :recordpid user "ACKN User App"
if errorlevel 1 goto launchfail
start "ACKN Admin App" /min /d "%ROOT%admin" cmd /s /c ""%NODE%" "%ROOT%admin\node_modules\vite\bin\vite.js" preview --port 5175 --strictPort --host 127.0.0.1"
call :recordpid admin "ACKN Admin App"
if errorlevel 1 goto launchfail

echo Starting, please wait (the first start can take a minute)...
set "N=0"
:wait
curl.exe -s -f -m 3 -o nul http://127.0.0.1:8000/health
if not errorlevel 1 goto up
call :isours backend "ACKN Backend"
if "%MINE%"=="0" goto crashed
set /a N+=1
if %N% GEQ 30 goto timeout
ping -n 3 127.0.0.1 >nul
goto wait

:crashed
echo ERROR: the backend stopped right after starting. See backend\logs\app.log
echo Run stop.bat to clean up.
set "RC=1"
goto done

:timeout
echo ERROR: backend did not answer within 60 seconds. See backend\logs\app.log
echo Run stop.bat to clean up.
set "RC=1"
goto done

:launchfail
echo ERROR: could not start a process. Run stop.bat to clean up.
set "RC=1"
goto done

:up
start "" "http://localhost:5174"
:urls
echo.
echo User app : http://localhost:5174
echo Admin app: http://localhost:5175
echo Stop with stop.bat
goto done

:isours
rem Sets MINE=1 only when the PID in .run\NAME.pid is a live cmd.exe whose window title is ours
rem (%~2). A recycled PID (after a crash or power-off) belongs to some other program: not ours.
set "P="
set "MINE=0"
if exist "%RUN%\%~1.pid" set /p P=<"%RUN%\%~1.pid"
if not defined P exit /b 0
tasklist /FI "PID eq %P%" /FI "IMAGENAME eq cmd.exe" /FI "WINDOWTITLE eq %~2*" /FO CSV /NH 2>nul | find """%P%""" >nul && set "MINE=1"
exit /b 0

:probe
set "L="
call :isours %~1 "%~3"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R /C:":%~2 .*LISTENING"') do set "L=%%a"
if "%MINE%"=="1" (
  set /a LIVE+=1
  if defined L set /a UP+=1
) else (
  if exist "%RUN%\%~1.pid" del "%RUN%\%~1.pid" >nul 2>nul
  if defined L set "BUSY=%BUSY% %~2"
)
exit /b 0

:recordpid
set "PIDX="
set "T=0"
:recordloop
for /f "tokens=2 delims=," %%p in ('tasklist /FI "IMAGENAME eq cmd.exe" /FI "WINDOWTITLE eq %~2*" /FO CSV /NH 2^>nul ^| find "cmd.exe"') do set "PIDX=%%~p"
if defined PIDX goto recorded
set /a T+=1
if %T% GEQ 15 exit /b 1
ping -n 2 127.0.0.1 >nul
goto recordloop
:recorded
>"%RUN%\%~1.pid" echo %PIDX%
exit /b 0

:done
echo "%cmdcmdline:"='%" | find /i "/c ''" >nul && pause
exit /b %RC%
