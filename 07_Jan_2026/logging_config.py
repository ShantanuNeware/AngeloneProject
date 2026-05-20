import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from datetime import datetime


def setup_logging(log_dir: str = "logs", filename: str | None = None, level=logging.DEBUG,
                  maxBytes: int = 10 * 1024 * 1024, backupCount: int = 5):
    """Configure root logging:

    - Creates `log_dir` if missing
    - Writes logs to a time-stamped file with rotation
    - Adds a console handler (INFO level)
    - Redirects sys.stdout/sys.stderr to the logger so print() also goes to the file
    Returns the full path to the logfile.
    """
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    if filename is None:
        filename = datetime.now().strftime("app_%Y%m%d_%H%M%S.log")

    logfile = os.path.join(log_dir, filename)

    root = logging.getLogger()
    root.setLevel(level)

    # Remove any existing handlers to avoid duplicate logs
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter("%(asctime)s %(threadName)s %(levelname)s: %(message)s")

    fh = RotatingFileHandler(logfile, maxBytes=maxBytes, backupCount=backupCount, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(level)
    root.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)
    root.addHandler(ch)

    # Redirect stdout/stderr to logging so print() output is captured
    class StreamToLogger:
        def __init__(self, logger, level=logging.INFO):
            self.logger = logger
            self.level = level

        def write(self, buf):
            if not buf:
                return
            for line in buf.rstrip().splitlines():
                # Avoid logging pure newline
                if line:
                    self.logger.log(self.level, line)

        def flush(self):
            return

    sys.stdout = StreamToLogger(root, logging.INFO)
    sys.stderr = StreamToLogger(root, logging.ERROR)

    # Capture warnings module messages
    logging.captureWarnings(True)

    root.info(f"Logging initialized. Log file: {logfile}")
    return logfile
