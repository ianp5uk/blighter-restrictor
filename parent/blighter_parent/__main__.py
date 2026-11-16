# -----------------------------------------------------------------------------
# Blighter Restrictor - entry point.
# Purpose: allows "python3 -m blighter_parent" and is the PyInstaller entry
# script for the Windows build.
# -----------------------------------------------------------------------------
from blighter_parent.app import main

if __name__ == "__main__":
    main()
