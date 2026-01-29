import hashlib
import os
import shlex
import shutil
import sys
from typing import Dict, Optional

from core import config


def list_desktop_files() -> list[str]:
    paths = [
        "/usr/share/applications",
        "/usr/local/share/applications",
        os.path.join(config.get_home_dir(), ".local", "share", "applications"),
        os.path.join(config.get_home_dir(), "Desktop"),
        "/var/lib/snapd/desktop/applications",
    ]
    results: list[str] = []
    for base in paths:
        if not os.path.isdir(base):
            continue
        for entry in os.listdir(base):
            if entry.endswith(".desktop"):
                results.append(os.path.join(base, entry))
    return results


def normalize_for_match(command: str) -> str:
    if not command:
        return ""
    try:
        parts = shlex.split(command)
    except ValueError:
        return command.strip()
    filtered = [part for part in parts if not part.startswith("%")]
    return " ".join(filtered).strip()


class DesktopManager:
    def normalize_app(self, app_command: str) -> str:
        from core import policy
        try:
            return policy.normalize_command(app_command)
        except Exception:
            return app_command.strip()

    def desktop_dir(self) -> str:
        return os.path.join(config.get_home_dir(), ".local", "share", "applications")

    def default_desktop_path(self, app_command: str) -> str:
        os.makedirs(self.desktop_dir(), exist_ok=True)
        key = self.normalize_app(app_command)
        name = os.path.basename(shlex.split(key)[0]) if key else "app"
        safe = f"lemux-{name}"
        suffix = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
        return os.path.join(self.desktop_dir(), f"{safe}-{suffix}.desktop")

    def python_exec(self) -> str:
        return config.get_python_executable()

    def cli_path(self) -> str:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cli.py"))

    def desktop_name(self, app_command: str) -> str:
        base = self._find_desktop_display_name(app_command)
        if not base:
            try:
                base = os.path.basename(shlex.split(app_command)[0])
            except Exception:
                base = os.path.basename(app_command)
        if not base:
            base = "Application"
        return f"{base} (Lemux)"

    def desktop_icon(self, app_command: str) -> str:
        try:
            base = os.path.basename(shlex.split(app_command)[0])
        except Exception:
            base = os.path.basename(app_command)
        return base or "application-x-executable"

    def _find_desktop_display_name(self, app_command: str) -> Optional[str]:
        candidates = list_desktop_files()
        app_exec = self._exec_basename(app_command)
        app_full = self._exec_path(app_command)
        app_norm = normalize_for_match(app_command)
        for path in candidates:
            data = self._parse_desktop_file(path)
            if not data:
                continue
            exec_name = data.get("Exec", "")
            try_exec = data.get("TryExec", "")
            wm_class = data.get("StartupWMClass", "")
            exec_base = self._exec_basename(exec_name)
            exec_full = self._exec_path(exec_name)
            try_base = self._exec_basename(try_exec)
            try_full = self._exec_path(try_exec)
            exec_norm = normalize_for_match(exec_name)
            wm_norm = (wm_class or "").lower()
            if (
                exec_base == app_exec
                or exec_full == app_full
                or try_base == app_exec
                or try_full == app_full
                or (app_norm and exec_norm and exec_norm.startswith(app_norm))
                or (app_norm and exec_norm and app_norm.startswith(exec_norm))
                or (wm_norm and wm_norm in app_command.lower())
            ):
                name = data.get("Name", "")
                if name:
                    return name.strip()
        return None

    def _parse_desktop_file(self, path: str) -> Optional[Dict[str, str]]:
        data: Dict[str, str] = {}
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                in_desktop_entry = False
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("[") and line.endswith("]"):
                        in_desktop_entry = line == "[Desktop Entry]"
                        if not in_desktop_entry and data:
                            break
                        continue
                    if not in_desktop_entry or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    if key in ("Name", "Exec", "TryExec", "StartupWMClass") and key not in data:
                        data[key] = value.strip()
        except OSError:
            return None
        return data

    def _exec_basename(self, command: str) -> str:
        if not command:
            return ""
        try:
            parts = shlex.split(command)
        except ValueError:
            return os.path.basename(command.strip())
        if not parts:
            return ""
        return os.path.basename(parts[0])

    def _exec_path(self, command: str) -> str:
        if not command:
            return ""
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = [command.strip()]
        if not parts:
            return ""
        candidate = parts[0]
        if os.path.isabs(candidate):
            return os.path.realpath(candidate)
        resolved = shutil.which(candidate)
        return os.path.realpath(resolved) if resolved else ""

    def get_desktop_entry(self, app_command: str) -> Optional[str]:
        config_data = config.get_config()
        entries = config_data.get("desktop_entries", {})
        return entries.get(self.normalize_app(app_command))

    def set_desktop_entry(self, app_command: str, path: str) -> None:
        config_data = config.get_config()
        entries = config_data.get("desktop_entries", {})
        entries[self.normalize_app(app_command)] = path
        config_data["desktop_entries"] = entries
        config.set_config(config_data)

    def remove_desktop_entry(self, app_command: str) -> None:
        config_data = config.get_config()
        entries = config_data.get("desktop_entries", {})
        key = self.normalize_app(app_command)
        if key in entries:
            entries.pop(key, None)
            config_data["desktop_entries"] = entries
            config.set_config(config_data)

    def create_desktop_entry(self, app_command: str) -> str:
        key = self.normalize_app(app_command)
        existing = self.get_desktop_entry(app_command)
        path = existing or self.default_desktop_path(app_command)
        os.makedirs(os.path.dirname(path), exist_ok=True)

        # Wrap in sh -c to ensure environment variables like DISPLAY and XAUTHORITY
        # are expanded from the launching shell/environment before pkexec runs.
        # We also pass LEMUX_INVOKING_USER explicitly to ensure we know who called us.
        inner_cmd = " ".join([
            "pkexec",
            "env",
            "DISPLAY=$DISPLAY",
            "XAUTHORITY=$XAUTHORITY",
            "LEMUX_INVOKING_USER=$(id -un)",
            self.python_exec(),
            self.cli_path(),
            "start",
            "--app",
            shlex.quote(app_command),
        ])
        # Escape double quotes for the outer sh -c string
        inner_cmd_escaped = inner_cmd.replace('"', '\\"')
        exec_line = f'sh -c "{inner_cmd_escaped}"'

        content = "\n".join([
            "[Desktop Entry]",
            f"Name={self.desktop_name(app_command)}",
            f"Exec={exec_line}",
            f"Icon={self.desktop_icon(app_command)}",
            "Type=Application",
            "Terminal=false",
            "Categories=Network;Utility;",
            "",
        ])

        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)

        self.set_desktop_entry(app_command, path)
        return path

    def delete_desktop_entry(self, app_command: str) -> None:
        path = self.get_desktop_entry(app_command)
        if path and os.path.exists(path):
            os.remove(path)
        self.remove_desktop_entry(app_command)

    def list_desktop_entries(self) -> Dict[str, str]:
        config_data = config.get_config()
        return dict(config_data.get("desktop_entries", {}))

    def ensure_desktop_entry(self, app_command: str) -> Optional[str]:
        path = self.get_desktop_entry(app_command)
        if not path:
            return None
        if not os.path.exists(path):
            return self.create_desktop_entry(app_command)
        return path
