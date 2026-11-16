# -----------------------------------------------------------------------------
# Blighter Restrictor - access to the shared domain rules.
# Purpose: import common/domains.py whether running from the packaged app
# (where the build copies it into this package) or straight from the source
# tree (where it lives in ../../common).
# -----------------------------------------------------------------------------
import os
import sys

try:
    from . import domains  # noqa: F401  (packaged)
except ImportError:  # running from source
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "common"))
    import domains  # noqa: F401

__all__ = ["domains"]
