@echo off
REM End-to-end demo of the whole pipeline on fully synthetic data.
REM Usage: run_demo.bat [small^|full]   (default: small)
setlocal
cd /d "%~dp0"

set PROFILE=%1
if "%PROFILE%"=="" set PROFILE=small
set PY=%PYTHON%
if "%PY%"=="" set PY=python

echo ==^> 1/6  Generating synthetic dataset (profile: %PROFILE%)
%PY% tools\generate_synthetic_data.py --profile %PROFILE%
if errorlevel 1 goto :error

echo ==^> 2/6  Creating database schema and reference tables
%PY% -m netsurvey.db.create_db
if errorlevel 1 goto :error

echo ==^> 3/6  Loading unmanaged / other devices
%PY% -m netsurvey.db.load_other_devices_json_to_db
if errorlevel 1 goto :error

echo ==^> 4/6  Loading validated managed-switch JSON
%PY% -m netsurvey.db.load_validated_json_to_db
if errorlevel 1 goto :error

echo ==^> 5/6  Generating topology diagrams
%PY% tools\generate_demo_diagrams.py
if errorlevel 1 echo    skipped - install networkx and pydot to enable diagrams

echo ==^> 6/6  Building the unassigned-networks report
%PY% -m netsurvey.reporting.extract_unassigned_networks
if errorlevel 1 goto :error

echo.
echo Demo build complete.
echo   Database : network_survey.db
echo   Diagrams : network_diagrams_pydot_final\
echo   Report   : unassigned_networks_GROUPED_REPORT.csv
goto :eof

:error
echo.
echo Demo build FAILED.
exit /b 1
