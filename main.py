"""Run 老必灯, the desktop keyboard lighting application."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "老必灯"
DATA_DIR.mkdir(parents=True, exist_ok=True)
handler = RotatingFileHandler(DATA_DIR / "runtime.log", maxBytes=512_000,
                              backupCount=2, encoding="utf-8")
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
logging.getLogger("vgn-ripple").addHandler(handler)
logging.getLogger("vgn-ripple").setLevel(logging.INFO)


def log_unhandled(error_type, error, trace):
    logging.getLogger("vgn-ripple").error("Unhandled error", exc_info=(error_type, error, trace))


sys.excepthook = log_unhandled


if __name__ == "__main__":
    from ui_app import run
    raise SystemExit(run(preview="--preview" in sys.argv))
