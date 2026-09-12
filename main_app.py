"""Convenience launcher for the survey GUI.

The application itself lives in netsurvey/gui/main_app.py; this thin launcher exists so
that the familiar 'python main_app.py' command and PyInstaller keep working.
"""
from netsurvey.gui.main_app import main

if __name__ == "__main__":
    main()
