# -----------------------------------------------------------------------------
# Blighter Restrictor - entry point.
# Purpose: allows "python3 -m blighter_parent" and is the PyInstaller entry
# script for the Windows build.  Because the Windows app has no console, any
# start-up failure is written to startup.log in the settings folder
# (%APPDATA%\BlighterRestrictor); with --self-test a hang is recorded there too.
# -----------------------------------------------------------------------------
import os
import sys
import traceback


def _settings_dir():
    if sys.platform.startswith("win"):
        d = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "BlighterRestrictor")
    else:
        d = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                         "blighter-restrictor")
    os.makedirs(d, exist_ok=True)
    return d


def _run():
    log = None
    if sys.stderr is None or "--self-test" in sys.argv:
        log = open(os.path.join(_settings_dir(), "startup.log"), "w", encoding="utf-8", buffering=1)
        if sys.stderr is None:
            sys.stderr = log
        if sys.stdout is None:
            sys.stdout = log
        log.write("starting\n")
    if "--self-test" in sys.argv and log:
        import faulthandler
        faulthandler.dump_traceback_later(25, exit=True, file=log)
    try:
        from blighter_parent.app import main
        if log:
            log.write("imports ok\n")
        main()
    except SystemExit:
        raise
    except BaseException:
        if log:
            traceback.print_exc(file=log)
        raise


if __name__ == "__main__":
    _run()
