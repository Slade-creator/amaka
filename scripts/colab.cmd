@echo off
rem Thin cmd.exe shim so `colab` works without remembering the WSL path.
rem Put this folder on PATH, then:  colab new --gpu T4
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0colab.ps1" %*
exit /b %ERRORLEVEL%
