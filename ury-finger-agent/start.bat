@echo off
rem URY Finger Agent — launcher
rem Avoids batch's classic parens-in-path footguns: every conditional is
rem opened with a literal opening paren on the same line, and we never
rem rely on `if defined ... if exist ...` chained patterns.

setlocal

set "AGENT_JAR=%~dp0ury-finger-agent.jar"
set "ZKFINGER_DIR=C:\Program Files (x86)\FPOnline\bin\ZKFinger"
set "QZ_JAVA=C:\Program Files\QZ Tray\runtime\bin\java.exe"

if not exist "%AGENT_JAR%" goto :no_jar
if not exist "%ZKFINGER_DIR%" goto :no_dlls

rem Pick a java.exe — explicit goto-based flow, no chained ifs.
set "JAVA_EXE="
if not "%JAVA_HOME%"=="" if exist "%JAVA_HOME%\bin\java.exe" set "JAVA_EXE=%JAVA_HOME%\bin\java.exe"
if "%JAVA_EXE%"=="" if exist "%QZ_JAVA%" set "JAVA_EXE=%QZ_JAVA%"
if "%JAVA_EXE%"=="" call :find_java
if "%JAVA_EXE%"=="" goto :no_java

echo Starting URY Finger Agent...
echo   Java: %JAVA_EXE%
echo   Jar:  %AGENT_JAR%
echo   DLLs: %ZKFINGER_DIR%
echo.

cd /d "%ZKFINGER_DIR%"
rem Library path needs System32 (where libzkfp.dll is installed by the
rem ISSOnline driver) AND ZKFinger\ (transitive deps for ZKFPCap.dll).
"%JAVA_EXE%" -Djava.library.path="%SystemRoot%\System32;%ZKFINGER_DIR%" -jar "%AGENT_JAR%" %*
goto :eof

:find_java
for /f "delims=" %%j in ('where java 2^>nul') do (
  if "%JAVA_EXE%"=="" set "JAVA_EXE=%%j"
)
goto :eof

:no_jar
echo ERROR: ury-finger-agent.jar not found next to this script.
echo Expected: %AGENT_JAR%
pause
exit /b 1

:no_dlls
echo ERROR: ZKFinger native DLLs not found at:
echo   %ZKFINGER_DIR%
echo Install the ISSOnline driver first.
pause
exit /b 1

:no_java
echo ERROR: No Java runtime found.
echo Install QZ Tray ^(comes with Java 11^), or set JAVA_HOME.
pause
exit /b 1
