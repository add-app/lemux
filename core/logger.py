import os
import datetime as dt
import pwd
from typing import Optional

from core import config


class LemuxLogger:
    def __init__(self, name: str, log_path: Optional[str] = None) -> None:
        self.name = name
        self.log_path = log_path or os.path.join(config.config_dir(), "lemux.log")
        self._clear_log()

    def _clear_log(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, "w", encoding="utf-8"):
                pass
            user = config.get_invoking_user()
            try:
                uid = pwd.getpwnam(user).pw_uid
                gid = pwd.getpwnam(user).pw_gid
                os.chown(self.log_path, uid, gid)
            except KeyError:
                pass
        except OSError:
            pass

    def _write(self, level: str, message: str) -> None:
        timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{timestamp} [{self.name}] {level}: {message}\n"
        try:
            os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line)
            user = config.get_invoking_user()
            try:
                uid = pwd.getpwnam(user).pw_uid
                gid = pwd.getpwnam(user).pw_gid
                os.chown(self.log_path, uid, gid)
            except KeyError:
                pass
        except OSError:
            pass

    def debug(self, message: str) -> None:
        debug_enabled = config.get_config().get("debug", False) or os.environ.get("LEMUX_DEBUG") == "1"
        if debug_enabled:
            self._write("DEBUG", message)

    def info(self, message: str) -> None:
        self._write("INFO", message)

    def warn(self, message: str) -> None:
        self._write("WARN", message)

    def error(self, message: str) -> None:
        self._write("ERROR", message)


logger = LemuxLogger("lemux")
