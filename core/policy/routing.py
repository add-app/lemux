import ipaddress
import os
from typing import Tuple


class RoutingManager:
    def __init__(self, run_command) -> None:
        self._run_command = run_command

    def parse_ipv4_info(self, iface: str) -> Tuple[str, str, str]:
        addr_out = self._run_command(["ip", "-4", "addr", "show", "dev", iface]).stdout
        ip_with_cidr = ""
        for line in addr_out.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                ip_with_cidr = line.split()[1]
                break
        if not ip_with_cidr:
            raise RuntimeError(f"No IPv4 address found for interface {iface}")

        gateway = ""
        gw_out = self._run_command(["ip", "-4", "route", "show", "default", "dev", iface]).stdout
        for line in gw_out.splitlines():
            parts = line.split()
            if "via" in parts:
                gateway = parts[parts.index("via") + 1]
                break
        if not gateway:
            gw_all = self._run_command(["ip", "-4", "route", "show", "default"]).stdout
            for line in gw_all.splitlines():
                if f"dev {iface}" in line:
                    parts = line.split()
                    if "via" in parts:
                        gateway = parts[parts.index("via") + 1]
                        break
        if not gateway:
            raise RuntimeError(f"No IPv4 gateway found for interface {iface}")

        network = str(ipaddress.ip_interface(ip_with_cidr).network)
        return ip_with_cidr, gateway, network

    def parse_ipv6_info(self, iface: str) -> Tuple[str, str, str]:
        addr_out = self._run_command(["ip", "-6", "addr", "show", "dev", iface], suppress_errors=True).stdout
        ip_with_cidr = ""
        if addr_out:
            for line in addr_out.splitlines():
                line = line.strip()
                if line.startswith("inet6 ") and "scope global" in line:
                    ip_with_cidr = line.split()[1]
                    break
        if not ip_with_cidr:
            return "", "", ""

        gateway = ""
        gw_out = self._run_command(["ip", "-6", "route", "show", "default", "dev", iface], suppress_errors=True).stdout
        if gw_out:
            for line in gw_out.splitlines():
                parts = line.split()
                if "via" in parts:
                    gateway = parts[parts.index("via") + 1]
                    break
        
        # Link-local gateway if no global default
        if not gateway:
             gw_out = self._run_command(["ip", "-6", "route", "show", "dev", iface], suppress_errors=True).stdout
             # Sometimes default gateway is link-local fe80::...
             pass

        if not gateway:
             # Try generic default search
             gw_all = self._run_command(["ip", "-6", "route", "show", "default"], suppress_errors=True).stdout
             for line in gw_all.splitlines():
                if f"dev {iface}" in line:
                    parts = line.split()
                    if "via" in parts:
                        gateway = parts[parts.index("via") + 1]
                        break

        if not gateway:
             return "", "", ""

        # Calculate network? IPv6 subnets are usually /64 but parsing is safer
        # But for PBR, we mainly need default route.
        network = "::/0" # Placeholder or derived
        try:
             network = str(ipaddress.ip_interface(ip_with_cidr).network)
        except Exception:
             pass
             
        return ip_with_cidr, gateway, network

    def ensure_rt_table(self, table_id: int, table_name: str) -> None:
        rt_tables = "/etc/iproute2/rt_tables"
        rt_dir = os.path.dirname(rt_tables)
        if not os.path.isdir(rt_dir):
            os.makedirs(rt_dir, exist_ok=True)
        if not os.path.exists(rt_tables):
            with open(rt_tables, "w", encoding="utf-8") as f:
                f.write("# Lemux routing tables\n")
        with open(rt_tables, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        entry = f"{table_id} {table_name}"
        if entry not in lines:
            with open(rt_tables, "a", encoding="utf-8") as f:
                f.write(f"\n{entry}\n")

    def ensure_interface_routes(self, iface: str, table_name: str, table_id: int) -> None:
        _ip_with_cidr, gateway, network = self.parse_ipv4_info(iface)
        self.ensure_rt_table(table_id, table_name)
        self._run_command(["ip", "route", "replace", network, "dev", iface, "table", table_name])
        self._run_command(["ip", "route", "replace", "default", "via", gateway, "dev", iface, "table", table_name])
        self._run_command(["sysctl", "-w", f"net.ipv4.conf.{iface}.rp_filter=2"])
        self._run_command(["sysctl", "-w", "net.ipv4.conf.all.rp_filter=2"])
        
        # IPv6
        ip6, gw6, net6 = self.parse_ipv6_info(iface)
        if ip6 and gw6:
             self._run_command(["ip", "-6", "route", "replace", net6, "dev", iface, "table", table_name])
             self._run_command(["ip", "-6", "route", "replace", "default", "via", gw6, "dev", iface, "table", table_name])

    def cleanup_rt_tables(self) -> None:
        rt_tables = "/etc/iproute2/rt_tables"
        if not os.path.exists(rt_tables):
            return
        with open(rt_tables, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        remaining = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                remaining.append(line)
                continue
            parts = stripped.split()
            if len(parts) == 2 and parts[1].startswith("lemux_"):
                continue
            remaining.append(line)
        with open(rt_tables, "w", encoding="utf-8") as f:
            f.write("\n".join(remaining) + "\n")

    def ensure_ip_rule(self, mark: str, table_name: str, priority: int) -> None:
        rules = self._run_command(["ip", "rule", "show"]).stdout
        rule_line = f"fwmark {mark} lookup {table_name}"
        if rule_line in rules:
            return
        self._run_command(["ip", "rule", "add", "fwmark", mark, "lookup", table_name, "priority", str(priority)])
        self._run_command(["ip", "-6", "rule", "add", "fwmark", mark, "lookup", table_name, "priority", str(priority)], suppress_errors=True)
        self._run_command(["ip", "route", "flush", "cache"])

    def ensure_uid_rule(self, uid: int, table_name: str, priority: int) -> None:
        rules = self._run_command(["ip", "rule", "show"]).stdout
        rule_line = f"uidrange {uid}-{uid} lookup {table_name}"
        if rule_line in rules:
            return
        self._run_command([
            "ip",
            "rule",
            "add",
            "uidrange",
            f"{uid}-{uid}",
            "lookup",
            table_name,
            "priority",
            str(priority),
        ])
        self._run_command(["ip", "route", "flush", "cache"])
        
        # IPv6 rule
        rules6 = self._run_command(["ip", "-6", "rule", "show"], suppress_errors=True).stdout
        rule_line6 = f"uidrange {uid}-{uid} lookup {table_name}"
        if rule_line6 not in (rules6 or ""):
             self._run_command([
                "ip", "-6",
                "rule",
                "add",
                "uidrange",
                f"{uid}-{uid}",
                "lookup",
                table_name,
                "priority",
                str(priority),
            ], suppress_errors=True)

    def delete_uid_rule(self, uid: int, table_name: str) -> None:
        self._run_command(["ip", "rule", "del", "uidrange", f"{uid}-{uid}", "lookup", table_name])
        self._run_command(["ip", "-6", "rule", "del", "uidrange", f"{uid}-{uid}", "lookup", table_name], suppress_errors=True)
