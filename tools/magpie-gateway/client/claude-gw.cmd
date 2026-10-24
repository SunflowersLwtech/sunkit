@echo off
rem claude-gw (Windows) - one Claude Code session through the magpie gateway; plain `claude` stays on Anthropic.
rem Same as client/claude-gw: %USERPROFILE%\.claude\magpie-settings.json goes in with --settings,
rem Opus 5.5 unless --model is given, and --channels (which takes every word after it) goes last.
setlocal
set "GW=%USERPROFILE%\.claude\magpie-settings.json"
if not exist "%GW%" (
  echo claude-gw: no %GW% 1>&2
  exit /b 1
)
set "MODEL=--model claude-opus-5-5"
echo. %* | findstr /C:"--model" >nul && set "MODEL="
set "CH="
if exist "%USERPROFILE%\.claude-mesh\config.json" set "CH=--channels plugin:mesh@sunkit"
echo. %* | findstr /C:" -p" /C:"--print" /C:"--channels" /C:" -h" /C:"--help" /C:" -v" /C:"--version" >nul && set "CH="
claude --settings "%GW%" %MODEL% %* %CH%
