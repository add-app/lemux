import os
import sys
import shutil
import subprocess
import shlex
import signal
import time
import pwd
from typing import Any, Dict, Optional, Tuple

from core.logger import logger
from core.interface import get_interface_dns
from core import config

class ProcessManager:
    def __init__(
        self,
        run_command,
        env,
        acl,
        audio,
        state_manager,
    ) -> None:
        self._run_command = run_command
        self._env = env
        self._acl = acl
        self._audio = audio
        self._state = state_manager

        self._state = state_manager

    def normalize_command(self, command: str) -> str:
        parts = shlex.split(command)
        return " ".join(shlex.quote(part) for part in parts)

    def split_command(self, command: str) -> tuple[str, list[str], str]:
        parts = shlex.split(command)
        if not parts:
            raise ValueError("Empty application command.")
        binary = parts[0]
        args = parts[1:]
        if not os.path.exists(binary):
            resolved = shutil.which(binary)
            if not resolved:
                raise FileNotFoundError(f"Application not found: {binary}")
            binary = resolved
        normalized = self.normalize_command(" ".join([binary, *args]))
        return binary, args, normalized

    def split_command_loose(self, command: str) -> tuple[str, list[str], str]:
        parts = shlex.split(command)
        if not parts:
            raise ValueError("Empty application command.")
        binary = parts[0]
        args = parts[1:]
        normalized = self.normalize_command(" ".join([binary, *args]))
        return binary, args, normalized

    def build_command(self, app_entry: Dict[str, Any]) -> str:
        binary = app_entry.get("binary")
        args = app_entry.get("arguments", [])
        if binary:
            parts = [binary, *args]
            return " ".join(shlex.quote(part) for part in parts)
        return app_entry.get("command", "")

    def create_system_user(self, username: str, home_dir: str) -> Tuple[str, int]:
        try:
            pw = pwd.getpwnam(username)
            return pw.pw_name, pw.pw_uid
        except KeyError:
            pass

        self._run_command([
            "useradd", "--system", "--create-home",
            "--home", home_dir,
            "--shell", "/usr/sbin/nologin",
            username,
        ])
        pw = pwd.getpwnam(username)
        return pw.pw_name, pw.pw_uid

    def ensure_app_dirs(self, home_dir: str, owner: str) -> None:
        paths = [
            home_dir,
            os.path.join(home_dir, ".config"),
            os.path.join(home_dir, ".cache"),
            os.path.join(home_dir, ".local", "share"),
            os.path.join(home_dir, ".local", "share", "applications"),
        ]
        for path in paths:
            os.makedirs(path, exist_ok=True)
        self._run_command(["chown", "-R", f"{owner}:{owner}", home_dir])

    def _ensure_app_home(self, app_entry: Dict[str, Any]) -> Dict[str, Any]:
        if app_entry.get("use_user_home"):
            pw = pwd.getpwnam(app_entry["user"])
            app_entry["home"] = pw.pw_dir
            app_entry["uid"] = pw.pw_uid
            return app_entry
        expected_home = self._env.app_home_dir(app_entry["user"])
        try:
            pw = pwd.getpwnam(app_entry["user"])
            if pw.pw_dir != expected_home:
                self._run_command(["usermod", "-d", expected_home, app_entry["user"]])
        except KeyError:
            pass
        current_home = app_entry.get("home")
        if current_home and current_home != expected_home and os.path.isdir(current_home) and not os.path.exists(expected_home):
            try:
                shutil.move(current_home, expected_home)
            except Exception:
                pass
        app_entry["home"] = expected_home
        os.makedirs(expected_home, exist_ok=True)
        self.ensure_app_dirs(expected_home, app_entry["user"])
        self._acl.ensure_shared_access(expected_home, app_entry["user"])
        return app_entry

    def _persist_app_home(self, app_entry: Dict[str, Any]) -> None:
        state = self._state.load_state()
        for app_key, entry in state.get("apps", {}).items():
            if entry.get("user") == app_entry.get("user"):
                entry["home"] = app_entry.get("home")
                break
        self._state.save_state(state)

    def _ensure_dbus_session(self, app_entry: Dict[str, Any]) -> Optional[str]:
        bus_path = f"/run/user/{app_entry['uid']}/bus"
        if os.path.exists(bus_path):
            return f"unix:path={bus_path}"
        if shutil.which("dbus-daemon"):
            try:
                subprocess.run(
                    [
                        "sudo",
                        "-u",
                        app_entry["user"],
                        "dbus-daemon",
                        "--session",
                        f"--address=unix:path={bus_path}",
                        "--fork",
                        "--nopidfile",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                return None
        if os.path.exists(bus_path):
            return f"unix:path={bus_path}"
        return None

    def launch_app(self, app_command: str, app_entry: Dict[str, Any], runtime_rules_callback=None) -> None:
        display = os.environ.get("DISPLAY")
        if not display:
            if os.path.exists("/tmp/.X11-unix/X0"):
                display = ":0"
            else:
                display = ":1"
        xauthority = os.environ.get("XAUTHORITY")
        if not xauthority:
            invoking_user, _ = self._env.get_invoking_user()
            xauthority = f"/home/{invoking_user}/.Xauthority"

        wayland_display = os.environ.get("WAYLAND_DISPLAY")
        if wayland_display:
            logger.warn("WAYLAND_DISPLAY detected; xhost skipped, X11 apps may fail without XWayland.")

        if display and xauthority and not wayland_display:
            try:
                subprocess.run(
                    ["xhost", f"+SI:localuser:{app_entry['user']}"],
                    env={**os.environ, "DISPLAY": display, "XAUTHORITY": xauthority},
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            except Exception:
                pass
            
            logger.warn("SECURITY WARNING: Application is running with X11 forwarding. It can potentially log keystrokes and capture screen content of other apps.")

        env = os.environ.copy()
        app_entry = self._ensure_app_home(app_entry)
        self._persist_app_home(app_entry)
        
        # Callback to AppManager to ensure routing rules before launch
        if runtime_rules_callback:
            runtime_rules_callback(app_entry)

        env["HOME"] = app_entry["home"]
        env["DISPLAY"] = display
        env["XAUTHORITY"] = xauthority
        env["USER"] = app_entry["user"]
        env["LOGNAME"] = app_entry["user"]
        env["XDG_CONFIG_HOME"] = os.path.join(app_entry["home"], ".config")
        env["XDG_DATA_HOME"] = os.path.join(app_entry["home"], ".local", "share")
        env["XDG_CACHE_HOME"] = os.path.join(app_entry["home"], ".cache")
        env["CHROME_CRASHPAD_PIPE_NAME"] = ""

        self.ensure_app_dirs(app_entry["home"], app_entry["user"])

        self._run_command(["mkdir", "-p", f"/run/user/{app_entry['uid']}"])
        self._run_command(["chown", f"{app_entry['user']}:{app_entry['user']}", f"/run/user/{app_entry['uid']}"])
        self._run_command(["chmod", "700", f"/run/user/{app_entry['uid']}"])
        env["XDG_RUNTIME_DIR"] = f"/run/user/{app_entry['uid']}"
        pulse_server, pipewire_remote = self._audio.ensure_audio_access(app_entry["user"])
        if pulse_server:
            env["PULSE_SERVER"] = pulse_server
            env["PULSE_RUNTIME_PATH"] = os.path.dirname(pulse_server.replace("unix:", "", 1))
        if pipewire_remote:
            env["PIPEWIRE_REMOTE"] = pipewire_remote
            invoking_uid = self._env.get_invoking_user()[1]
            env["PIPEWIRE_RUNTIME_DIR"] = f"/run/user/{invoking_uid}"
        session_bus = self._ensure_dbus_session(app_entry)
        if session_bus:
            env["DBUS_SESSION_BUS_ADDRESS"] = session_bus

        # Spawn ACL Keeper background worker
        try:
            _, inv_uid = self._env.get_invoking_user()
            
            # Ensure we run from project root so 'core' module is found
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            
            keeper_cmd = [
                "sudo",
                config.get_python_executable(),
                "-m", "core.policy.acl_keeper",
                "--host-uid", str(inv_uid),
                "--app-user", app_entry["user"]
            ]
            
            # Prepare environment with PYTHONPATH to ensure imports work
            keeper_env = os.environ.copy()
            if "PYTHONPATH" in keeper_env:
                keeper_env["PYTHONPATH"] = f"{project_root}:{keeper_env['PYTHONPATH']}"
            else:
                keeper_env["PYTHONPATH"] = project_root

            subprocess.Popen(
                keeper_cmd,
                cwd=project_root,
                env=keeper_env,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception as e:
            logger.error(f"Failed to start ACL keeper: {e}")

        cmd = ["sudo", "-u", app_entry["user"]]
        cmd.append("env")
        cmd.extend([
            f"HOME={env['HOME']}",
            f"DISPLAY={env['DISPLAY']}",
            f"XAUTHORITY={env['XAUTHORITY']}",
            f"XDG_RUNTIME_DIR={env['XDG_RUNTIME_DIR']}",
            f"USER={env['USER']}",
            f"LOGNAME={env['LOGNAME']}",
            f"XDG_CONFIG_HOME={env['XDG_CONFIG_HOME']}",
            f"XDG_DATA_HOME={env['XDG_DATA_HOME']}",
            f"XDG_CACHE_HOME={env['XDG_CACHE_HOME']}",
            f"DBUS_SESSION_BUS_ADDRESS={env.get('DBUS_SESSION_BUS_ADDRESS', '')}",
        ])
        audio_env = []
        for key in ("PULSE_SERVER", "PULSE_RUNTIME_PATH", "PIPEWIRE_REMOTE", "PIPEWIRE_RUNTIME_DIR"):
            value = env.get(key)
            if value:
                audio_env.append(f"{key}={value}")
        cmd.extend(audio_env)

        binary = app_entry.get("binary")
        args = app_entry.get("arguments", [])
        if binary:
            app_parts = [binary, *args]
        else:
            app_parts = shlex.split(app_command)
        if app_parts:
            bin_name = os.path.basename(app_parts[0]).lower()
            if any(token in bin_name for token in ("chrome", "chromium", "yandex")):
                for flag in ("--disable-crashpad", "--disable-crash-reporter", "--disable-breakpad", "--no-crashpad"):
                    if flag not in app_parts:
                        app_parts.append(flag)
                if app_entry.get("use_profile", False):
                    profile_dir = os.path.join(app_entry["home"], "browser-profile")
                    os.makedirs(profile_dir, exist_ok=True)
                    self._run_command(["chown", "-R", f"{app_entry['user']}:{app_entry['user']}", profile_dir])
                    if "--user-data-dir" not in app_parts:
                        app_parts.extend(["--user-data-dir", profile_dir])
                    if "--no-first-run" not in app_parts:
                        app_parts.append("--no-first-run")

        cmd.extend(app_parts)

        # DNS Leak Mitigation
        try:
            dns_servers = get_interface_dns(app_entry["iface"])
            if not dns_servers:
                # Fallback to privacy-respecting public DNS if no interface DNS found
                dns_servers = ["1.1.1.1", "1.0.0.1"]
            
            resolv_conf_path = os.path.join(f"/run/user/{app_entry['uid']}", "resolv.conf.lemux")
            with open(resolv_conf_path, "w") as f:
                for server in dns_servers:
                    f.write(f"nameserver {server}\n")
            
            # Wrap command in unshare to bind mount custom resolv.conf
            # We must escape the inner command because it executes inside sh -c "..."
            inner_cmd_str = " ".join(shlex.quote(p) for p in cmd)
            
            # Prepare bind mounts for Audio sockets to bypass directory permission issues
            bind_mounts = []
            
            # PulseAudio
            if env.get("PULSE_SERVER") and env["PULSE_SERVER"].startswith("unix:"):
                host_pulse = env["PULSE_SERVER"].replace("unix:", "", 1)
                app_pulse_dir = f"/run/user/{app_entry['uid']}/pulse"
                app_pulse_socket = os.path.join(app_pulse_dir, os.path.basename(host_pulse))
                
                # Update Env to point to new location
                env["PULSE_SERVER"] = f"unix:{app_pulse_socket}"
                env["PULSE_RUNTIME_PATH"] = app_pulse_dir
                
                bind_mounts.append(f"mkdir -p {app_pulse_dir}")
                bind_mounts.append(f"touch {app_pulse_socket}")
                bind_mounts.append(f"mount --bind {host_pulse} {app_pulse_socket}")

            # PipeWire
            if env.get("PIPEWIRE_REMOTE") and env["PIPEWIRE_REMOTE"].startswith("unix:"):
                host_pw = env["PIPEWIRE_REMOTE"].replace("unix:", "", 1)
                app_pw_dir =f"/run/user/{app_entry['uid']}"
                app_pw_socket = os.path.join(app_pw_dir, os.path.basename(host_pw))
                
                # Update Env
                env["PIPEWIRE_REMOTE"] = f"unix:{app_pw_socket}"
                env["PIPEWIRE_RUNTIME_DIR"] = app_pw_dir
                
                bind_mounts.append(f"touch {app_pw_socket}")
                bind_mounts.append(f"mount --bind {host_pw} {app_pw_socket}")
            
            setup_cmds = " && ".join(bind_mounts) if bind_mounts else "true"

            # Wrap command in unshare to bind mount custom resolv.conf AND audio sockets
            # We must escape the inner command because it executes inside sh -c "..."
            inner_cmd_str = " ".join(shlex.quote(p) for p in cmd)
            
            wrapper_cmd = [
                "sudo", "/usr/bin/unshare", "--mount", "--propagation", "private", "--", "sh", "-c",
                f"{setup_cmds} && mount --bind {resolv_conf_path} /etc/resolv.conf && exec {inner_cmd_str}"
            ]
            
            subprocess.Popen(wrapper_cmd, env=env, start_new_session=True, close_fds=True)

        except Exception as e:
            logger.error(f"Failed to setup DNS isolation: {e}. Falling back to standard launch.")
            subprocess.Popen(cmd, env=env, start_new_session=True, close_fds=True)

    def kill_app_processes(self, app_entry: Dict[str, Any], app_command_fallback: str) -> None:
        user = app_entry.get("user")
        uid = app_entry.get("uid")
        
        # Use explicitly configured binary if available to avoid parsing issues
        if app_entry.get("binary"):
            exe_path = app_entry["binary"]
        else:
            command = self.build_command(app_entry) or app_command_fallback
            try:
                exe_path = shlex.split(command)[0]
            except ValueError:
                exe_path = command.strip()
                
        exe_base = os.path.basename(exe_path)
        if os.path.isabs(exe_path):
            exe_path = os.path.realpath(exe_path)

        proc = subprocess.run(
            ["ps", "-eo", "pid,ppid,uid,command"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError("Failed to read process list.")

        ppid_map: Dict[int, list[int]] = {}
        matches: set[int] = set()
        for line in proc.stdout.splitlines()[1:]:
            parts = line.strip().split(maxsplit=3)
            if len(parts) < 4:
                continue
            pid_str, ppid_str, uid_str, cmdline = parts
            
            try:
                proc_uid = int(uid_str)
            except ValueError:
                continue
                
            if uid is not None and proc_uid != uid:
                continue
                
            try:
                pid = int(pid_str)
                ppid = int(ppid_str)
            except ValueError:
                continue
            ppid_map.setdefault(ppid, []).append(pid)
            
            cmd_head = cmdline.split(maxsplit=1)[0]
            cmd_base = os.path.basename(cmd_head)
            
            # Fallback heuristic: normalize names (remove extension, replace - with _)
            # This handles yandex-browser-stable vs yandex_browser mismatch
            norm_exe = exe_base.lower().replace("-", "_").rsplit(".", 1)[0]
            norm_cmd = cmd_base.lower().replace("-", "_").rsplit(".", 1)[0]
            
            if norm_exe and norm_cmd and (norm_exe in norm_cmd or norm_cmd in norm_exe):
                matches.add(pid)
            if exe_path and exe_path in cmdline:
                matches.add(pid)
            elif cmd_base == exe_base:
                matches.add(pid)
            elif exe_base and exe_base in cmdline:
                matches.add(pid)

        if not matches:
            raise RuntimeError("No running processes matched this application.")

        to_stop: set[int] = set()

        def collect_children(pid: int) -> None:
            for child in ppid_map.get(pid, []):
                if child in to_stop:
                    continue
                to_stop.add(child)
                collect_children(child)

        for pid in matches:
            to_stop.add(pid)
            collect_children(pid)

        for pid in to_stop:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                continue
            except PermissionError:
                continue

        time.sleep(0.5)

        for pid in list(to_stop):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                continue
            except PermissionError:
                continue
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                continue
            except PermissionError:
                continue
