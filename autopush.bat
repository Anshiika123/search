@echo off
echo Auto-push watcher started. Press Ctrl+C to stop.
echo Watching for changes in: %~dp0
cd /d %~dp0

:loop
timeout /t 30 /nobreak >nul
git diff --quiet && git diff --cached --quiet
if errorlevel 1 (
    echo [%time%] Changes detected - pushing...
    git add -A
    git commit -m "auto: save %date% %time%"
    git push origin main
    echo [%time%] Pushed!
) else (
    echo [%time%] No changes.
)
goto loop
