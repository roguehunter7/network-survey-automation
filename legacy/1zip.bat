@echo off
echo Checking for 7-Zip installation...

:: Check multiple possible 7-Zip locations
set "ZIP_PATH="
if exist "C:\Program Files\7-Zip\7z.exe" set "ZIP_PATH=C:\Program Files\7-Zip\7z.exe"
if exist "C:\Program Files (x86)\7-Zip\7z.exe" set "ZIP_PATH=C:\Program Files (x86)\7-Zip\7z.exe"
if exist "%ProgramFiles%\7-Zip\7z.exe" set "ZIP_PATH=%ProgramFiles%\7-Zip\7z.exe"
if exist "%ProgramFiles(x86)%\7-Zip\7z.exe" set "ZIP_PATH=%ProgramFiles(x86)%\7-Zip\7z.exe"

:: Check if 7z is in PATH
where 7z >nul 2>&1
if %errorlevel% equ 0 set "ZIP_PATH=7z"

if "%ZIP_PATH%"=="" (
    echo Error: 7-Zip not found!
    echo Please install 7-Zip or check installation path.
    echo.
    pause
    exit /b 1
)

echo Found 7-Zip at: %ZIP_PATH%
echo.

:: Delete existing archive if it exists
if exist "abc.zip" (
    echo Deleting existing abc.zip...
    del "abc.zip"
)

echo Creating abc.zip...
echo.

:: Create the archive with verbose output
"%ZIP_PATH%" a -tzip abc.zip data survey_outputs validated_jsons_api_structured_MAC_CHUNKED_MP gemini.py config.py llm_prompt_stage1a.txt llm_prompt_stage1b.txt llm_prompt_stage2_mac.txt unified_processor.py utils.py

if %errorlevel% equ 0 (
    echo.
    echo Archive created successfully!
    echo Location: %cd%\abc.zip
) else (
    echo.
    echo Error creating archive! Error code: %errorlevel%
)

echo.
pause