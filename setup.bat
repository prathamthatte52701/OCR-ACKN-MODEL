@echo off
setlocal
set "ROOT=%~dp0"
set "RC=0"
set "PY=%ROOT%venv\Scripts\python.exe"

if not exist "%PY%" (
  echo ERROR: venv not found. Create it first with: python -m venv venv
  set "RC=1"
  goto done
)
where node >nul 2>nul
if errorlevel 1 (
  echo ERROR: Node.js not found on PATH. Install Node 20.19+ or 22.12+ from nodejs.org.
  set "RC=1"
  goto done
)
where npm >nul 2>nul
if errorlevel 1 (
  echo ERROR: npm not found on PATH. Reinstall Node.js 20.19+ or 22.12+.
  set "RC=1"
  goto done
)
node -e "var v=process.versions.node.split('.').map(Number);var m=v[0],n=v[1];process.exit(((m==20&&n>=19)||(m==22&&n>=12)||m>22)?0:1)"
if errorlevel 1 (
  echo ERROR: Node version too old. Vite 8 needs Node 20.19+ or 22.12+ - install a newer Node.
  set "RC=1"
  goto done
)
if not exist "%ROOT%backend\.env" (
  echo ERROR: backend\.env is missing. Copy backend\.env.example to backend\.env and fill it in.
  set "RC=1"
  goto done
)
set "SZ=0"
for %%F in ("%ROOT%backend\.env") do set "SZ=%%~zF"
if "%SZ%"=="0" (
  echo ERROR: backend\.env is empty. Fill it in from backend\.env.example.
  set "RC=1"
  goto done
)

echo [1/3] Installing backend packages...
"%PY%" -m pip install -r "%ROOT%backend\requirements.txt"
if errorlevel 1 (
  echo ERROR: backend package install failed.
  set "RC=1"
  goto done
)

set "APP=frontend"
call :webapp
if not "%RC%"=="0" goto done
set "APP=admin"
call :webapp
if not "%RC%"=="0" goto done

echo.
echo Setup complete. Now run start.bat
goto done

:webapp
echo Building %APP% app...
pushd "%ROOT%%APP%"
if errorlevel 1 (
  echo ERROR: folder %APP% not found.
  set "RC=1"
  exit /b 1
)
if exist package-lock.json (
  call npm ci
) else (
  call npm install
)
if errorlevel 1 (
  echo ERROR: npm install failed in %APP%.
  popd
  set "RC=1"
  exit /b 1
)
call npm run build
if errorlevel 1 (
  echo ERROR: build failed in %APP%.
  popd
  set "RC=1"
  exit /b 1
)
popd
exit /b 0

:done
echo "%cmdcmdline:"='%" | find /i "/c ''" >nul && pause
exit /b %RC%
