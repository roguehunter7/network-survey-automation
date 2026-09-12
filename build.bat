@echo off
REM Builds the survey GUI into a single Windows executable.
cd /d "%~dp0"

echo Current working directory: %CD%
echo.

echo Running PyInstaller...
pyinstaller --noconfirm --clean --onefile --windowed ^
    --paths . ^
    --add-data "data;data" ^
    --add-data "netsurvey/llm/prompts;netsurvey/llm/prompts" ^
    main_app.py

echo.
if errorlevel 1 (
    echo PyInstaller FAILED with errors.
) else (
    echo PyInstaller COMPLETED successfully.
    echo Output in: %CD%\dist
)
echo.
pause
