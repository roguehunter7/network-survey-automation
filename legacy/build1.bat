@echo off
REM Ensures the script operates from its own directory.
cd /d "%~dp0"

echo Current working directory: %CD%
echo.

echo Locating ntc-templates data path...
REM This command finds where the ntc-templates package is installed.
for /f "delims=" %%i in ('python -c "import os; import ntc_templates; print(os.path.join(ntc_templates.__path__[0], 'templates'))"') do set "NTC_PATH=%%i"

if not defined NTC_PATH (
    echo ERROR: Could not find the ntc-templates library path.
    echo Please ensure 'ntc-templates' is installed in your Python environment.
    pause
    exit /b 1
)

echo Found path: %NTC_PATH%
echo.

echo Running PyInstaller...
REM The modified command now includes --copy-metadata for the required packages.
pyinstaller --noconfirm --clean --onefile --windowed ^
--hidden-import "ntc_templates.parse" ^
--hidden-import "serial.tools.list_ports" ^
--hidden-import "config" ^
--hidden-import "data_manager" ^
--hidden-import "utils" ^
--add-data "%NTC_PATH%;ntc_templates/templates" ^
--add-data "data;data" ^
--copy-metadata "ntc-templates" ^
--copy-metadata "importlib-metadata" ^
new1.py

echo.
if errorlevel 1 (
    echo PyInstaller FAILED with errors.
) else (
    echo PyInstaller COMPLETED successfully.
    echo Output in: %CD%\dist
)
echo.
pause
