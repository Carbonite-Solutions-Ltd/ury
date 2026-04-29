@echo off
rem URY Finger Agent — auto-start installer
rem
rem Drops a shortcut to start.bat into the current user's Startup folder
rem so the agent launches automatically when they sign in to Windows.
rem Uses PowerShell to create the .lnk because cmd has no shortcut tool.
rem Window starts minimised so the console doesn't pop up in the user's face.

setlocal

set "AGENT_DIR=%~dp0"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT=%STARTUP%\URY Finger Agent.lnk"

if not exist "%AGENT_DIR%start.bat" (
  echo ERROR: install.bat must sit next to start.bat in the same folder.
  echo Found install.bat in: %AGENT_DIR%
  pause
  exit /b 1
)

if not exist "%STARTUP%" (
  mkdir "%STARTUP%"
)

rem WindowStyle 7 = Minimised. Saves the user from a console window
rem stealing focus on every login.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$sc = $ws.CreateShortcut('%SHORTCUT%');" ^
  "$sc.TargetPath = '%AGENT_DIR%start.bat';" ^
  "$sc.WorkingDirectory = '%AGENT_DIR%';" ^
  "$sc.WindowStyle = 7;" ^
  "$sc.Description = 'URY Finger Agent — fingerprint capture for the URY POS';" ^
  "$sc.Save()"

if not exist "%SHORTCUT%" (
  echo ERROR: failed to create the startup shortcut.
  pause
  exit /b 1
)

echo.
echo  =====================================================================
echo  URY Finger Agent will now start automatically when you sign in.
echo  =====================================================================
echo.
echo  Shortcut created at:
echo    %SHORTCUT%
echo.
echo  Starting the agent now (minimised) so you can use it immediately...
start "" /MIN "%AGENT_DIR%start.bat"

echo.
echo  Done. Open http://127.0.0.1:9994/ in a browser to confirm it's
echo  running. To remove auto-start later, run uninstall.bat.
echo.
pause
