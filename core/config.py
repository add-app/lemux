import json
import os
import pwd
import sys
from typing import Any, Dict


class Configuration:
    def get_python_executable(self) -> str:
        # 1. Attempt to find venv python relative to this file
        # project/core/config.py -> project/venv/bin/python
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        venv_python = os.path.join(base_dir, "venv", "bin", "python")
        if os.path.exists(venv_python):
            return venv_python
            
        venv_python3 = os.path.join(base_dir, "venv", "bin", "python3")
        if os.path.exists(venv_python3):
            return venv_python3

        # 2. Check VIRTUAL_ENV environment variable
        venv_env = os.environ.get("VIRTUAL_ENV")
        if venv_env:
            candidate = os.path.join(venv_env, "bin", "python")
            if os.path.exists(candidate):
                return candidate
        
        # 3. Fallback to current executable
        return sys.executable

    def get_invoking_user(self) -> str:
        env_user = os.environ.get("LEMUX_INVOKING_USER")
        if env_user and not env_user.startswith("%"):
            try:
                pwd.getpwnam(env_user)
                return env_user
            except KeyError:
                pass
        
        sudo_user = os.environ.get("SUDO_USER")
        if sudo_user:
            return sudo_user
        pkexec_uid = os.environ.get("PKEXEC_UID")
        if pkexec_uid:
            try:
                return pwd.getpwuid(int(pkexec_uid)).pw_name
            except KeyError:
                pass
        return pwd.getpwuid(os.getuid()).pw_name

    def get_home_dir(self) -> str:
        user = self.get_invoking_user()
        return pwd.getpwnam(user).pw_dir

    def config_dir(self) -> str:
        return os.path.join(self.get_home_dir(), ".config", ".lemux")

    def config_path(self) -> str:
        return os.path.join(self.config_dir(), "config.json")

    def ensure_config_dir(self) -> None:
        config_dir = self.config_dir()
        os.makedirs(config_dir, exist_ok=True)
        user = self.get_invoking_user()
        try:
            uid = pwd.getpwnam(user).pw_uid
            gid = pwd.getpwnam(user).pw_gid
            os.chown(config_dir, uid, gid)
        except PermissionError:
            pass

    def get_config(self) -> Dict[str, Any]:
        self.ensure_config_dir()
        path = self.config_path()
        if not os.path.exists(path):
            return {"debug": False, "users": [], "selected_user": "Auto", "desktop_entries": {}}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return {"debug": False}
        if "debug" not in data:
            data["debug"] = False
        if "users" not in data:
            data["users"] = []
        if "selected_user" not in data:
            data["selected_user"] = "Auto"
        if "desktop_entries" not in data:
            data["desktop_entries"] = {}
        return data

    def set_config(self, config: Dict[str, Any]) -> None:
        self.ensure_config_dir()
        path = self.config_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, sort_keys=True)

    def set_debug(self, enabled: bool) -> None:
        config = self.get_config()
        config["debug"] = bool(enabled)
        self.set_config(config)

    def set_users(self, users: list[str]) -> None:
        config = self.get_config()
        config["users"] = list(users)
        self.set_config(config)

    def set_selected_user(self, user: str) -> None:
        config = self.get_config()
        config["selected_user"] = user
        self.set_config(config)

    def prune_users(self) -> None:
        config = self.get_config()
        users = config.get("users", [])
        keep = []
        for user in users:
            try:
                pwd.getpwnam(user)
            except KeyError:
                continue
            keep.append(user)
        if keep != users:
            config["users"] = keep
            if config.get("selected_user") not in keep:
                config["selected_user"] = "Auto"
            self.set_config(config)



_CONFIG = Configuration()


def get_invoking_user() -> str:
    return _CONFIG.get_invoking_user()


def get_home_dir() -> str:
    return _CONFIG.get_home_dir()


def config_dir() -> str:
    return _CONFIG.config_dir()


def config_path() -> str:
    return _CONFIG.config_path()


def ensure_config_dir() -> None:
    _CONFIG.ensure_config_dir()


def get_config() -> Dict[str, Any]:
    return _CONFIG.get_config()


def set_config(config: Dict[str, Any]) -> None:
    _CONFIG.set_config(config)


def set_debug(enabled: bool) -> None:
    _CONFIG.set_debug(enabled)


def set_users(users: list[str]) -> None:
    _CONFIG.set_users(users)


def set_selected_user(user: str) -> None:
    _CONFIG.set_selected_user(user)


def prune_users() -> None:
    _CONFIG.prune_users()


def get_python_executable() -> str:
    return _CONFIG.get_python_executable()
