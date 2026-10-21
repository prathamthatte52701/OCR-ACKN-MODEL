@echo off
setlocal
set "ROOT=%~dp0"
set "RUN=%ROOT%.run"
set "RC=0"
set "FOUND=0"

call :stopone backend 8000 "ACKN Backend"
call :stopone user 5174 "ACKN User App"
call :stopone admin 5175 "ACKN Admin App"

set "LEFT="
for %%p in (8000 5174 5175) do call :chk %%p
if "%FOUND%"=="0" (
  echo Nothing was running.
) else (
  echo Stopped. If a document is being processed it is requeued at the next start.
)
if defined LEFT echo Note: still in use by other programs, left alone: port%LEFT%
goto done

:chk
netstat -ano | findstr /R /C:":%1 .*LISTENING" >nul && set "LEFT=%LEFT% %1"
exit /b 0

:isours
rem Sets MINE=1 only when the PID in .run\NAME.pid is a live cmd.exe whose window title is ours
rem (%~2). A recycled PID (after a crash or power-off) belongs to some other program: not ours.
set "P="
set "MINE=0"
if exist "%RUN%\%~1.pid" set /p P=<"%RUN%\%~1.pid"
if not defined P exit /b 0
tasklist /FI "PID eq %P%" /FI "IMAGENAME eq cmd.exe" /FI "WINDOWTITLE eq %~2*" /FO CSV /NH 2>nul | find """%P%""" >nul && set "MINE=1"
exit /b 0

:stopone
call :isours %~1 "%~3"
if "%MINE%"=="1" (
  taskkill /PID %P% /T /F >nul 2>nul
  set "FOUND=1"
  echo Stopped %~1 [PID %P%].
)
if exist "%RUN%\%~1.pid" del "%RUN%\%~1.pid" >nul 2>nul
set "L="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R /C:":%~2 .*LISTENING"') do set "L=%%a"
if not defined L exit /b 0
rem Something still listens (pid file missing or stale): kill it ONLY if its command line contains
rem this folder. This rare path uses PowerShell, which can be slow to start on some PCs.
set "OURS="
for /f "usebackq delims=" %%c in (`powershell -NoProfile -Command "$id=[int]$env:L; Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -eq $id -and $_.CommandLine -and $_.CommandLine.IndexOf($env:ROOT,[StringComparison]::OrdinalIgnoreCase) -ge 0 } | ForEach-Object { 'OURS' }"`) do set "OURS=%%c"
if defined OURS (
  taskkill /PID %L% /T /F >nul 2>nul
  set "FOUND=1"
  echo Stopped %~1 on port %~2 [PID %L%].
) else (
  echo Port %~2 is used by another program [PID %L%] - left alone.
)
exit /b 0

:done
echo "%cmdcmdline:"='%" | find /i "/c ''" >nul && pause
exit /b %RC%
