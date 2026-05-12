import os
import hashlib
import pwd
from typing import Any, Dict, Optional, Tuple

from core.logger import logger
from core import config
from core.desktop import DesktopManager
from core.policy.state import StateManager
from core.policy.process import ProcessManager

class AppManager:
    def __init__(
        self,
        run_command,
        env,
        acl,
        audio,
        nft,
        routing,
        iptables,
        base_table_id: int,
        base_priority: int,
    ) -> None:
        self._run_command = run_command
        self._env = env
        self._acl = acl
        self._audio = audio
        self._nft = nft
        self._routing = routing
        self._iptables = iptables
        self._base_table_id = base_table_id
        self._base_priority = base_priority
        self._desktop = DesktopManager()
        
        self._state = StateManager(run_command, env)
        self._process = ProcessManager(run_command, env, acl, audio, self._state)

    # Delegation to ProcessManager
    def normalize_command(self, command: str) -> str:
        return self._process.normalize_command(command)

    def split_command(self, command: str) -> tuple[str, list[str], str]:
        return self._process.split_command(command)

    def split_command_loose(self, command: str) -> tuple[str, list[str], str]:
        return self._process.split_command_loose(command)

    def build_command(self, app_entry: Dict[str, Any]) -> str:
        return self._process.build_command(app_entry)

    def _create_system_user(self, username: str, home_dir: str) -> Tuple[str, int]:
        return self._process.create_system_user(username, home_dir)

    def _ensure_app_dirs(self, home_dir: str, owner: str) -> None:
        self._process.ensure_app_dirs(home_dir, owner)

    def _ensure_app_home(self, app_entry: Dict[str, Any]) -> Dict[str, Any]:
        return self._process._ensure_app_home(app_entry)

    def _persist_app_home(self, app_entry: Dict[str, Any]) -> None:
        return self._process._persist_app_home(app_entry)

    def _ensure_dbus_session(self, app_entry: Dict[str, Any]) -> Optional[str]:
        return self._process._ensure_dbus_session(app_entry)

    # Delegation to StateManager
    def _ensure_state_dir(self) -> None:
        self._state._ensure_state_dir()

    def _load_state(self) -> Dict[str, Any]:
        return self._state.load_state()

    def _save_state(self, state: Dict[str, Any]) -> None:
        self._state.save_state(state)

    def list_assignments(self) -> Dict[str, Any]:
        return self._state.load_state()

    # Core Logic
    def _alloc_interface_entry(self, state: Dict[str, Any], iface: str) -> Dict[str, Any]:
        if iface in state["interfaces"]:
            return state["interfaces"][iface]

        used_ids = {entry["table_id"] for entry in state["interfaces"].values()}
        table_id = self._base_table_id
        while table_id in used_ids:
            table_id += 1

        mark_val = hex(0x100 + len(state["interfaces"]) + 1)
        table_name = f"lemux_{iface}"
        entry = {"table_id": table_id, "table_name": table_name, "mark": mark_val, "iface_name": iface}
        state["interfaces"][iface] = entry
        return entry


    def _ensure_runtime_rules(self, app_entry: Dict[str, Any]) -> None:
        state = self._state.load_state()
        iface = app_entry.get("iface")
        if not iface:
            for entry in state.get("apps", {}).values():
                if entry.get("user") == app_entry.get("user"):
                    iface = entry.get("iface")
                    break
        if not iface:
            logger.warn("No interface found for app entry; rules not refreshed.")
            return
        iface_entry = state.get("interfaces", {}).get(iface)
        if not iface_entry:
            iface_entry = self._alloc_interface_entry(state, iface)
            self._state.save_state(state)
        gateway = self._routing.ensure_interface_routes(
            iface,
            iface_entry["table_name"],
            iface_entry["table_id"],
            fallback_gateway=iface_entry.get("gateway4"),
        )
        if gateway and iface_entry.get("gateway4") != gateway:
            iface_entry["gateway4"] = gateway
            self._state.save_state(state)
        self._routing.ensure_ip_rule(
            iface_entry["mark"],
            iface_entry["table_name"],
            self._base_priority + iface_entry["table_id"],
        )
        self._routing.delete_fwmark_block_rule(iface_entry["mark"])
        self._nft.ensure_uid_mark(app_entry["uid"], iface_entry["mark"])
        self._iptables.ensure_uid_exclusion(app_entry["uid"])
        self._routing.ensure_uid_rule(
            app_entry["uid"],
            iface_entry["table_name"],
            self._base_priority + iface_entry["table_id"] - 1,
        )
        self._routing.ensure_uid_block_rule(
            app_entry["uid"],
            self._base_priority + iface_entry["table_id"] + 1,
        )

    def assign_app(
        self,
        app_command: str,
        iface: str,
        use_profile: Optional[bool] = None,
        existing_user: Optional[str] = None,
    ) -> Dict[str, Any]:
        # ... (start of assign_app logic is same)
        state = self._state.load_state()
        binary, args, normalized = self.split_command(app_command)

        if existing_user and not existing_user.startswith("lemux_"):
            raise ValueError("Only lemux_* users from configuration can be used.")

        if normalized in state["apps"]:
            if state["apps"][normalized]["iface"] != iface:
                self.deassign_app(normalized)
                state = self._state.load_state()
            elif existing_user and state["apps"][normalized].get("user") != existing_user:
                self.deassign_app(normalized)
                state = self._state.load_state()

        iface_entry = self._alloc_interface_entry(state, iface)
        gateway = self._routing.ensure_interface_routes(
            iface,
            iface_entry["table_name"],
            iface_entry["table_id"],
            fallback_gateway=iface_entry.get("gateway4"),
        )
        if gateway:
            iface_entry["gateway4"] = gateway
        self._routing.ensure_ip_rule(
            iface_entry["mark"],
            iface_entry["table_name"],
            self._base_priority + iface_entry["table_id"],
        )
        self._routing.delete_fwmark_block_rule(iface_entry["mark"])

        app_key = normalized
        if app_key not in state["apps"]:
             # ... (logic to create user or get user, same)
            if existing_user:
                try:
                    pw = pwd.getpwnam(existing_user)
                except KeyError as exc:
                    raise ValueError(f"User not found: {existing_user}") from exc
                cfg_users = config.get_config().get("users", [])
                if existing_user not in cfg_users:
                    raise ValueError("User is not registered in configuration.")
                state["apps"][app_key] = {
                    "iface": iface,
                    "user": pw.pw_name,
                    "uid": pw.pw_uid,
                    "home": pw.pw_dir,
                    "binary": binary,
                    "arguments": args,
                    "use_profile": False,
                    "use_user_home": True,
                }
            else:
                user_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
                username = f"lemux_{user_hash}"
                home_dir = self._env.app_home_dir(username)
                os.makedirs(home_dir, exist_ok=True)
                _, uid = self._create_system_user(username, home_dir)
                self._ensure_app_dirs(home_dir, username)
                self._acl.ensure_shared_access(home_dir, username)
                state["apps"][app_key] = {
                    "iface": iface,
                    "user": username,
                    "uid": uid,
                    "home": home_dir,
                    "binary": binary,
                    "arguments": args,
                    "use_profile": False,
                    "use_user_home": False,
                }
                cfg_users = config.get_config().get("users", [])
                if username not in cfg_users:
                    cfg_users.append(username)
                    config.set_users(cfg_users)

        if existing_user and app_key in state["apps"]:
             # ... (update existing)
            try:
                pw = pwd.getpwnam(existing_user)
            except KeyError as exc:
                raise ValueError(f"User not found: {existing_user}") from exc
            cfg_users = config.get_config().get("users", [])
            if existing_user not in cfg_users:
                raise ValueError("User is not registered in configuration.")
            state["apps"][app_key]["user"] = pw.pw_name
            state["apps"][app_key]["uid"] = pw.pw_uid
            state["apps"][app_key]["home"] = pw.pw_dir
            state["apps"][app_key]["use_user_home"] = True

        if app_key in state["apps"]:
            state["apps"][app_key]["binary"] = binary
            state["apps"][app_key]["arguments"] = args

        app_entry = self._ensure_app_home(state["apps"][app_key])
        if use_profile is not None:
            app_entry["use_profile"] = bool(use_profile)

        self._nft.ensure_uid_mark(app_entry["uid"], iface_entry["mark"])
        self._iptables.ensure_uid_exclusion(app_entry["uid"])
        self._routing.ensure_uid_rule(
            app_entry["uid"],
            iface_entry["table_name"],
            self._base_priority + iface_entry["table_id"] - 1,
        )
        self._routing.ensure_uid_block_rule(
            app_entry["uid"],
            self._base_priority + iface_entry["table_id"] + 1,
        )
        self._state.save_state(state)
        return app_entry

    def deassign_app(self, app_command: str) -> None:
        state = self._state.load_state()
        normalized = self.normalize_command(app_command)
        
        target_key = None
        if normalized in state["apps"]:
            target_key = normalized
        else:
            try:
                _, _, resolved = self.split_command(app_command)
                if resolved in state["apps"]:
                    target_key = resolved
            except Exception:
                pass
                
        if not target_key:
             raise KeyError("Application is not assigned.")

        app_entry = state["apps"].pop(target_key)
        try:
            self._desktop.delete_desktop_entry(self.build_command(app_entry) or target_key)
        except Exception:
            pass
        iface = app_entry["iface"]
        iface_entry = state["interfaces"].get(iface)
        if iface_entry:
            self._nft.delete_uid_mark(app_entry["uid"], iface_entry["mark"])
            self._iptables.delete_uid_exclusion(app_entry["uid"])
            self._routing.delete_uid_rule(app_entry["uid"], iface_entry["table_name"])
            self._routing.delete_uid_block_rule(app_entry["uid"])
        if iface_entry:
            remaining = [app for app in state["apps"].values() if app["iface"] == iface]
            if not remaining:
                self._routing.delete_ip_rule(iface_entry["mark"], iface_entry["table_name"])
                self._routing.delete_fwmark_block_rule(iface_entry["mark"])
                self._run_command(["ip", "route", "flush", "table", iface_entry["table_name"]])

        self._state.save_state(state)

    def reset_all(self) -> None:
        state = self._state.load_state()
        for app_entry in state.get("apps", {}).values():
            try:
                self._desktop.delete_desktop_entry(self.build_command(app_entry))
            except Exception:
                pass
        for iface_entry in state["interfaces"].values():
            self._routing.delete_ip_rule(iface_entry["mark"], iface_entry["table_name"])
            self._run_command(["ip", "route", "flush", "table", iface_entry["table_name"]])
        for app_entry in state.get("apps", {}).values():
            iface = app_entry.get("iface")
            iface_entry = state.get("interfaces", {}).get(iface)
            if iface_entry:
                self._routing.delete_uid_rule(app_entry["uid"], iface_entry["table_name"])
                self._routing.delete_uid_block_rule(app_entry["uid"])
                self._iptables.delete_uid_exclusion(app_entry["uid"])
        table_list = self._run_command(["nft", "list", "tables"]).stdout
        if f"table inet lemux" in table_list:
            self._run_command(["nft", "delete", "table", "inet", "lemux"])
        for iface_entry in state["interfaces"].values():
            self._routing.delete_fwmark_block_rule(iface_entry["mark"])
        self._routing.flush_block_table()

        self._routing.cleanup_rt_tables()
        self._state.save_state({"interfaces": {}, "apps": {}})


    def launch_app(self, app_command: str, app_entry: Dict[str, Any]) -> None:
        self._process.launch_app(app_command, app_entry, runtime_rules_callback=self._ensure_runtime_rules)

    def stop_app(self, app_command: str) -> None:
        state = self._state.load_state()
        normalized = self.normalize_command(app_command)
        app_entry = state.get("apps", {}).get(normalized)
        if not app_entry:
            for key, entry in state.get("apps", {}).items():
                if self.build_command(entry) == app_command or key == app_command:
                    app_entry = entry
                    break
        if not app_entry:
            raise KeyError("Application is not assigned.")

        self._process.kill_app_processes(app_entry, app_command)
