"""AirHomeCaster launcher: adds the repo root to sys.path then runs the GUI.

Also captures stderr to airhomecaster_error.log for post-mortem debugging.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

ERR_LOG = os.path.join(HERE, "airhomecaster_error.log")
_err = open(ERR_LOG, "w", encoding="utf-8", buffering=1)
sys.stderr = _err
sys.excepthook = lambda *a: (_err.write(repr(a) + "\n"), _err.flush())

import faulthandler
faulthandler.enable(_err)

from airhomecaster.app import main  # noqa: E402

if __name__ == "__main__":
    main()
