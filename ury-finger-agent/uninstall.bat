@echo off
rem URY Finger Agent — auto-start uninstaller
rem
rem Removes the Startup-folder shortcut. Doesn't delete the agent
rem files, just stops it from launching automatically. To stop a
rem currently-running agent, close its console window or end the
rem java.exe process in Task Manager.

setlocal

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT=%STARTUP%\URY Finger Agent.lnk"

if exist "%SHORTCUT%" (
  del "%SHORTCUT%"
  echo Removed startup shortcut.
) else (
  echo Startup shortcut was not present.
)

echo.
echo The agent will not auto-start on next login. To stop a currently-
echo running agent, close its console window or end "java.exe" via
echo Task Manager. The agent files in this folder are unchanged.
echo.
pause
