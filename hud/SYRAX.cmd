@echo off
rem Double-click to launch the SYRAX HUD as a fullscreen desktop app (needs: npm install in this folder once).
rem Clear ELECTRON_RUN_AS_NODE in case it leaks in from VS Code terminals; it makes Electron act as plain Node.
set ELECTRON_RUN_AS_NODE=
rem "%~dp0." not "%~dp0": the trailing backslash of %~dp0 would escape the closing quote.
start "" "%~dp0node_modules\electron\dist\electron.exe" "%~dp0."
