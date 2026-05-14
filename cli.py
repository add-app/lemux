#!/usr/bin/env python3
import os
import sys
sys.dont_write_bytecode = True
import argparse
import shlex

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

from core.interface import get_active_interfaces
from core import policy
from core.desktop import DesktopManager
from core import config


class LemuxCLI:
    def __init__(self) -> None:
        if os.geteuid() != 0:
            print("[X] This script must be run as root.")
            sys.exit(1)
        self.desktop = DesktopManager()

        self.parser = argparse.ArgumentParser(description="CLI for Lemux app routing.")
        subparsers = self.parser.add_subparsers(dest="command", help="Available commands")

        parser_networks = subparsers.add_parser("networks", help="List active network interfaces.")
        parser_networks.set_defaults(func=self.list_interfaces)

        parser_rules = subparsers.add_parser("rules", help="List current app routing rules.")
        parser_rules.set_defaults(func=self.list_rules)

        parser_assign = subparsers.add_parser("assign", help="Assign an application to an interface.")
        parser_assign.add_argument("--app", required=True, help="Command or path to the application.")
        parser_assign.add_argument("--iface", required=True, help="Name of the interface.")
        parser_assign.add_argument("--launch", action="store_true", help="Launch app after assignment.")
        parser_assign.add_argument("--profile", action="store_true", help="Use a dedicated browser profile for Chromium apps.")
        parser_assign.set_defaults(func=self.assign_app)

        parser_deassign = subparsers.add_parser("deassign", help="Remove an assignment by app command.")
        parser_deassign.add_argument("--app", required=True, help="Command or path to the application.")
        parser_deassign.set_defaults(func=self.deassign_app)

        parser_start = subparsers.add_parser("start", help="Start an assigned application.")
        parser_start.add_argument("--app", required=True, help="Command or path to the application.")
        parser_start.set_defaults(func=self.start_app)

        parser_reset = subparsers.add_parser("reset", help="Reset all Lemux rules.")
        parser_reset.set_defaults(func=self.reset_all)

        parser_desktop = subparsers.add_parser("desktop", help="Manage Lemux desktop entries.")
        desktop_sub = parser_desktop.add_subparsers(dest="desktop_cmd", help="Desktop commands")

        parser_desktop_list = desktop_sub.add_parser("list", help="List desktop entries.")
        parser_desktop_list.set_defaults(func=self.desktop_list)

        parser_desktop_create = desktop_sub.add_parser("create", help="Create a desktop entry for an assigned app.")
        parser_desktop_create.add_argument("--app", required=True, help="Command or path to the application.")
        parser_desktop_create.set_defaults(func=self.desktop_create)

        parser_desktop_delete = desktop_sub.add_parser("delete", help="Delete a desktop entry for an assigned app.")
        parser_desktop_delete.add_argument("--app", required=True, help="Command or path to the application.")
        parser_desktop_delete.set_defaults(func=self.desktop_delete)

        parser_desktop_set = desktop_sub.add_parser("set-path", help="Set a desktop entry path for an assigned app.")
        parser_desktop_set.add_argument("--app", required=True, help="Command or path to the application.")
        parser_desktop_set.add_argument("--path", required=True, help="Absolute path to the desktop file.")
        parser_desktop_set.set_defaults(func=self.desktop_set_path)

        parser_trace = subparsers.add_parser("trace", help="Run nftables trace for an app user.")
        parser_trace.add_argument("--app", required=True, help="Command or path to the application.")
        parser_trace.add_argument("--iface", required=False, help="Interface name (optional).")
        parser_trace.add_argument("--timeout", type=int, default=5, help="Trace capture timeout in seconds.")
        parser_trace.add_argument("--url", default="https://example.com", help="URL or IP to trace.")
        parser_trace.set_defaults(func=self.trace_app)

    def list_interfaces(self, _args: argparse.Namespace) -> None:
        print("--- Active Network Interfaces ---")
        interfaces = get_active_interfaces()
        if not interfaces:
            print("No active network interfaces found.")
            return

        for iface in interfaces:
            if iface['flag'] == 'UP' and iface['ip_addresses']:
                print(f"\nInterface: {iface['name']}")
                print(f"  Status: {iface['flag']}")
                print(f"  Type: {iface['type']}")
                print(f"  IP Addresses: {', '.join(iface['ip_addresses'])}")
                print(f"  Gateways: {', '.join(iface['gateways'] if iface['gateways'] else ['N/A'])}")

    def assign_app(self, args: argparse.Namespace) -> None:
        try:
            entry = policy.assign_app(args.app, args.iface, use_profile=args.profile)
            if args.launch:
                policy.launch_app(policy.build_command(entry) or args.app, entry)
            print(f"[✓] Assigned '{args.app}' to '{args.iface}'.")
        except Exception as e:
            print(f"[X] Failed to assign '{args.app}': {e}")

    def list_rules(self, _args: argparse.Namespace) -> None:
        state = policy.list_assignments()
        apps = state.get("apps", {})
        if not apps:
            print("No app rules found.")
            return
        print("--- App Rules ---")
        for app, entry in apps.items():
            iface = entry.get("iface", "-")
            user = entry.get("user", "-")
            uid = entry.get("uid", "-")
            binary = entry.get("binary", "-")
            arguments = entry.get("arguments", [])
            iface_entry = state.get("interfaces", {}).get(iface, {})
            mark = iface_entry.get("mark", "-")
            table = iface_entry.get("table_name", "-")
            priority = iface_entry.get("priority")
            rule = "-"
            if priority is not None:
                rule = str(priority)
            print(f"\nApp: {app}")
            print(f"  Binary: {binary}")
            if arguments:
                print(f"  Arguments: {' '.join(arguments)}")
            print(f"  User: {user} (uid={uid})")
            print(f"  Interface: {iface}")
            print(f"  Mark: {mark}")
            print(f"  Table: {table}")
            print(f"  Priority: {rule}")

    def deassign_app(self, args: argparse.Namespace) -> None:
        try:
            policy.deassign_app(args.app)
            print(f"[✓] Deassigned '{args.app}'.")
        except Exception as e:
            print(f"[X] Failed to deassign '{args.app}': {e}")

    def start_app(self, args: argparse.Namespace) -> None:
        try:
            state = policy.list_assignments()
            entry = self._find_app_entry(state.get("apps", {}), args.app)
            if not entry:
                print("[X] App is not assigned. Use 'assign' first.")
                return
            policy.launch_app(policy.build_command(entry) or args.app, entry)
            print(f"[✓] Started '{args.app}'.")
        except Exception as e:
            print(f"[X] Failed to start '{args.app}': {e}")

    def desktop_list(self, _args: argparse.Namespace) -> None:
        entries = self.desktop.list_desktop_entries()
        if not entries:
            print("No desktop entries found.")
            return
        print("--- Desktop Entries ---")
        for app, path in entries.items():
            if not os.path.exists(path):
                path = self.desktop.ensure_desktop_entry(app) or path
            exists = "yes" if os.path.exists(path) else "missing"
            print(f"\nApp: {app}")
            print(f"  Path: {path}")
            print(f"  Exists: {exists}")

    def desktop_create(self, args: argparse.Namespace) -> None:
        try:
            state = policy.list_assignments()
            normalized = policy.normalize_command(args.app)
            entry = state.get("apps", {}).get(normalized) or state.get("apps", {}).get(args.app)
            if not entry:
                print("[X] App is not assigned. Use 'assign' first.")
                return
            path = self.desktop.create_desktop_entry(policy.build_command(entry) or args.app)
            print(f"[✓] Desktop entry created: {path}")
        except Exception as e:
            print(f"[X] Failed to create desktop entry: {e}")

    def desktop_delete(self, args: argparse.Namespace) -> None:
        try:
            self.desktop.delete_desktop_entry(args.app)
            print(f"[✓] Desktop entry deleted for '{args.app}'.")
        except Exception as e:
            print(f"[X] Failed to delete desktop entry: {e}")

    def desktop_set_path(self, args: argparse.Namespace) -> None:
        try:
            state = policy.list_assignments()
            normalized = policy.normalize_command(args.app)
            entry = state.get("apps", {}).get(normalized) or state.get("apps", {}).get(args.app)
            if not entry:
                print("[X] App is not assigned. Use 'assign' first.")
                return
            path = os.path.abspath(args.path)
            if not path.endswith(".desktop"):
                print("[X] Desktop path must end with .desktop")
                return
            parent = os.path.dirname(path)
            if not os.path.isdir(parent):
                print(f"[X] Desktop directory does not exist: {parent}")
                return
            home_dir = config.get_home_dir()
            allowed_roots = {
                os.path.join(home_dir, ".local", "share", "applications"),
                os.path.join(home_dir, "Desktop"),
                home_dir,
                "/usr/share/applications",
                "/usr/local/share/applications",
            }
            if not any(os.path.commonpath([path, root]) == root for root in allowed_roots if os.path.isabs(root)):
                print("[X] Desktop path must be under your home or standard applications directories.")
                return
            self.desktop.set_desktop_entry(policy.build_command(entry) or args.app, path)
            print(f"[✓] Desktop path set: {path}")
        except Exception as e:
            print(f"[X] Failed to set desktop path: {e}")

    def _find_app_entry(self, apps: dict, app_command: str) -> dict | None:
        normalized = policy.normalize_command(app_command)
        entry = apps.get(normalized) or apps.get(app_command)
        if entry:
            return entry

        placeholder = self._normalize_with_placeholder(app_command)
        if placeholder and placeholder in apps:
            return apps.get(placeholder)

        app_match = self._normalize_for_lookup(app_command)
        for key, value in apps.items():
            if self._normalize_for_lookup(key) == app_match:
                return value
        return None

    def _normalize_with_placeholder(self, app_command: str) -> str | None:
        invoking_user = config.get_invoking_user()
        try:
            parts = shlex.split(app_command)
        except ValueError:
            return None
        if not parts:
            return None
        updated = [("%u" if part == invoking_user else part) for part in parts]
        rebuilt = " ".join(shlex.quote(part) for part in updated)
        return policy.normalize_command(rebuilt)

    def _normalize_for_lookup(self, command: str) -> str:
        try:
            parts = shlex.split(command)
        except ValueError:
            return command.strip()
        filtered = [part for part in parts if not part.startswith("%")]
        return policy.normalize_command(" ".join(shlex.quote(part) for part in filtered))

    def reset_all(self, _args: argparse.Namespace) -> None:
        try:
            policy.reset_all()
            print("[✓] All Lemux rules cleared.")
        except Exception as e:
            print(f"[X] Reset failed: {e}")

    def trace_app(self, args: argparse.Namespace) -> None:
        try:
            state = policy.list_assignments()
            entry = self._find_app_entry(state.get("apps", {}), args.app)
            if not entry and args.iface:
                entry = policy.assign_app(args.app, args.iface)
            if not entry:
                print("[X] App is not assigned. Provide --iface to assign temporarily.")
                return
            iface_entry = state.get("interfaces", {}).get(entry.get("iface"))
            mark = iface_entry.get("mark") if iface_entry else "0x0"
            output = policy.run_nft_trace_test(
                uid=entry["uid"],
                mark=mark,
                test_cmd=["sudo", "-u", entry["user"], "curl", "-4", args.url],
                timeout_sec=args.timeout,
            )
            print(output)
        except Exception as e:
            print(f"[X] Trace failed: {e}")

    def run(self) -> None:
        args = self.parser.parse_args()
        if hasattr(args, 'func'):
            args.func(args)
        else:
            self.parser.print_help()


def main() -> None:
    cli = LemuxCLI()
    cli.run()


if __name__ == "__main__":
    main()
