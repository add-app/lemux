import ipaddress
import os
import re
from typing import Optional, Tuple


class RoutingManager:
    BLOCK_TABLE_ID = 99
    BLOCK_TABLE_NAME = "lemux_block"
    MIN_DYNAMIC_PRIORITY = 100

    def __init__(self, run_command) -> None:
        self._run_command = run_command

    def parse_ipv4_info(self, iface: str, fallback_gateway: Optional[str] = None) -> Tuple[str, str, str]:
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
            gateway = self._get_nmcli_ipv4_gateway(iface)
        if not gateway and fallback_gateway:
            gateway = fallback_gateway
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

    def ensure_block_table(self) -> None:
        self.ensure_rt_table(self.BLOCK_TABLE_ID, self.BLOCK_TABLE_NAME)
        self._run_command(["ip", "route", "replace", "unreachable", "default", "table", self.BLOCK_TABLE_NAME])
        self._run_command(["ip", "-6", "route", "replace", "unreachable", "default", "table", self.BLOCK_TABLE_NAME], suppress_errors=True)

    def flush_block_table(self) -> None:
        self._run_command(["ip", "route", "flush", "table", self.BLOCK_TABLE_NAME], suppress_errors=True)
        self._run_command(["ip", "-6", "route", "flush", "table", self.BLOCK_TABLE_NAME], suppress_errors=True)

    def get_table_ipv4_gateway(self, table_name: str, iface: str) -> str:
        routes = self._run_command(["ip", "-4", "route", "show", "table", table_name], suppress_errors=True).stdout
        return self._extract_default_gateway(routes, iface)

    def get_main_ipv4_gateway(self, iface: str) -> str:
        routes = self._run_command(["ip", "-4", "route", "show", "default", "dev", iface], suppress_errors=True).stdout
        gateway = self._extract_default_gateway(routes, iface)
        if gateway:
            return gateway
        routes = self._run_command(["ip", "-4", "route", "show", "default"], suppress_errors=True).stdout
        gateway = self._extract_default_gateway(routes, iface)
        if gateway:
            return gateway
        return self._get_nmcli_ipv4_gateway(iface)

    def _get_nmcli_ipv4_gateway(self, iface: str) -> str:
        output = self._run_command(["nmcli", "-g", "IP4.GATEWAY", "device", "show", iface], suppress_errors=True).stdout
        for line in (output or "").splitlines():
            gateway = line.strip()
            if gateway and gateway != "--":
                return gateway
        return ""

    def _extract_default_gateway(self, routes: str, iface: str) -> str:
        for line in (routes or "").splitlines():
            parts = line.split()
            if not parts or parts[0] != "default":
                continue
            if f"dev {iface}" not in line or "via" not in parts:
                continue
            return parts[parts.index("via") + 1]
        return ""

    def ensure_interface_routes(
        self,
        iface: str,
        table_name: str,
        table_id: int,
        fallback_gateway: Optional[str] = None,
    ) -> str:
        cached_gateway = fallback_gateway or self.get_table_ipv4_gateway(table_name, iface)
        ip_with_cidr, gateway, network = self.parse_ipv4_info(iface, fallback_gateway=cached_gateway)
        source_ip = str(ipaddress.ip_interface(ip_with_cidr).ip)
        self.ensure_rt_table(table_id, table_name)
        self._run_command(["ip", "route", "replace", network, "dev", iface, "src", source_ip, "table", table_name])
        self._run_command(["ip", "route", "replace", "default", "via", gateway, "dev", iface, "src", source_ip, "table", table_name])
        self._run_command(["ip", "route", "replace", "unreachable", "default", "metric", "4278198272", "table", table_name])
        self._run_command(["sysctl", "-w", f"net.ipv4.conf.{iface}.rp_filter=2"])
        self._run_command(["sysctl", "-w", "net.ipv4.conf.all.rp_filter=2"])
        
        # IPv6
        ip6, gw6, net6 = self.parse_ipv6_info(iface)
        if ip6 and gw6:
             self._run_command(["ip", "-6", "route", "replace", net6, "dev", iface, "table", table_name])
             self._run_command(["ip", "-6", "route", "replace", "default", "via", gw6, "dev", iface, "table", table_name])
             self._run_command(["ip", "-6", "route", "replace", "unreachable", "default", "metric", "4278198272", "table", table_name], suppress_errors=True)
        else:
             # Prevent leak to VPN if no IPv6 on interface
             self._run_command(["ip", "-6", "route", "replace", "unreachable", "default", "table", table_name], suppress_errors=True)

        return gateway

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

    def choose_rule_priorities(self, table_name: str, table_id: int, fallback_base_priority: int) -> dict[str, int]:
        fallback_mark = fallback_base_priority + table_id
        existing_rules = self._run_command(["ip", "rule", "show"]).stdout
        used_priorities = self._parse_rule_priorities(existing_rules)
        interfering_priorities = self._find_interfering_rule_priorities(existing_rules)

        mark_priority = fallback_mark
        if interfering_priorities:
            earliest_interference = min(interfering_priorities)
            current_mark_priority = self._find_current_mark_priority(existing_rules, table_name)
            if current_mark_priority and current_mark_priority + 1 < earliest_interference:
                mark_priority = current_mark_priority
            else:
                candidate = earliest_interference - 2
                mark_priority = self._find_available_priority_block(candidate, used_priorities, fallback_mark)

        return {
            "uid": mark_priority - 1,
            "mark": mark_priority,
            "block": mark_priority + 1,
        }

    def _parse_rule_priorities(self, rules: str) -> set[int]:
        priorities = set()
        for line in (rules or "").splitlines():
            match = re.match(r"\s*(\d+):", line)
            if match:
                priorities.add(int(match.group(1)))
        return priorities

    def _find_interfering_rule_priorities(self, rules: str) -> list[int]:
        priorities = []
        for line in (rules or "").splitlines():
            match = re.match(r"\s*(\d+):", line)
            if not match:
                continue
            priority = int(match.group(1))
            if priority <= self.MIN_DYNAMIC_PRIORITY or priority >= 32766:
                continue
            if " lookup lemux_" in line or f" lookup {self.BLOCK_TABLE_NAME}" in line:
                continue
            if self._is_interfering_policy_rule(line):
                priorities.append(priority)
        return priorities

    def _find_current_mark_priority(self, rules: str, table_name: str) -> Optional[int]:
        for line in (rules or "").splitlines():
            match = re.match(r"\s*(\d+):", line)
            if not match:
                continue
            if "fwmark" in line and f" lookup {table_name}" in line:
                return int(match.group(1))
        return None

    def _is_interfering_policy_rule(self, rule: str) -> bool:
        if "suppress_prefixlength" in rule:
            return True
        if "not from all fwmark" in rule and " lookup " in rule:
            return True
        if "fwmark" in rule and " lookup " in rule:
            return True
        return False

    def _find_available_priority_block(
        self,
        preferred_mark_priority: int,
        used_priorities: set[int],
        fallback_mark_priority: int,
    ) -> int:
        mark_priority = preferred_mark_priority
        while mark_priority - 1 >= self.MIN_DYNAMIC_PRIORITY:
            block = {mark_priority - 1, mark_priority, mark_priority + 1}
            if not block & used_priorities:
                return mark_priority
            mark_priority -= 3
        return fallback_mark_priority

    def ensure_ip_rule(self, mark: str, table_name: str, priority: int) -> None:
        rules = self._run_command(["ip", "rule", "show"]).stdout
        rule_line = f"fwmark {mark} lookup {table_name}"
        if not self._has_rule_at_priority(rules, rule_line, priority):
            self.delete_ip_rule(mark, table_name)
            self._run_command(["ip", "rule", "add", "fwmark", mark, "lookup", table_name, "priority", str(priority)])

        rules6 = self._run_command(["ip", "-6", "rule", "show"], suppress_errors=True).stdout
        if not self._has_rule_at_priority(rules6 or "", rule_line, priority):
            self._run_command(["ip", "-6", "rule", "del", "fwmark", mark, "lookup", table_name], suppress_errors=True)
            self._run_command(["ip", "-6", "rule", "add", "fwmark", mark, "lookup", table_name, "priority", str(priority)], suppress_errors=True)
        self._run_command(["ip", "route", "flush", "cache"])

    def delete_ip_rule(self, mark: str, table_name: str) -> None:
        self._delete_lookup_rule(["fwmark", mark], table_name, ipv6=False)
        self._delete_lookup_rule(["fwmark", mark], table_name, ipv6=True)

    def ensure_uid_rule(self, uid: int, table_name: str, priority: int) -> None:
        rules = self._run_command(["ip", "rule", "show"]).stdout
        rule_line = f"uidrange {uid}-{uid} lookup {table_name}"
        if not self._has_rule_at_priority(rules, rule_line, priority):
            self.delete_uid_rule(uid, table_name)
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
        if not self._has_rule_at_priority(rules6 or "", rule_line6, priority):
             self._run_command(["ip", "-6", "rule", "del", "uidrange", f"{uid}-{uid}", "lookup", table_name], suppress_errors=True)
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

    def ensure_uid_block_rule(self, uid: int, priority: int) -> None:
        self.ensure_block_table()
        self._ensure_block_rule(["uidrange", f"{uid}-{uid}"], priority, ipv6=False)
        self._ensure_block_rule(["uidrange", f"{uid}-{uid}"], priority, ipv6=True)

    def _ensure_block_rule(self, selector: list[str], priority: int, ipv6: bool) -> None:
        cmd = ["ip"]
        if ipv6:
            cmd.append("-6")
        rules = self._run_command([*cmd, "rule", "show"], suppress_errors=ipv6).stdout or ""
        selector_text = " ".join(selector)
        rule_line = f"{selector_text} lookup {self.BLOCK_TABLE_NAME}"
        if self._has_rule_at_priority(rules, rule_line, priority):
            return
        self._delete_block_rule(selector, ipv6)
        self._run_command(
            [*cmd, "rule", "add", *selector, "lookup", self.BLOCK_TABLE_NAME, "priority", str(priority)],
            suppress_errors=ipv6,
        )

    def _has_rule_at_priority(self, rules: str, rule_line: str, priority: int) -> bool:
        priority_prefix = f"{priority}:"
        for line in (rules or "").splitlines():
            if line.startswith(priority_prefix) and rule_line in line:
                return True
        return False

    def delete_uid_rule(self, uid: int, table_name: str) -> None:
        self._delete_lookup_rule(["uidrange", f"{uid}-{uid}"], table_name, ipv6=False)
        self._delete_lookup_rule(["uidrange", f"{uid}-{uid}"], table_name, ipv6=True)

    def delete_uid_block_rule(self, uid: int) -> None:
        self._delete_block_rule(["uidrange", f"{uid}-{uid}"], ipv6=False)
        self._delete_block_rule(["uidrange", f"{uid}-{uid}"], ipv6=True)

    def delete_fwmark_block_rule(self, mark: str) -> None:
        self._delete_block_rule(["fwmark", mark], ipv6=False)
        self._delete_block_rule(["fwmark", mark], ipv6=True)

    def _delete_block_rule(self, selector: list[str], ipv6: bool) -> None:
        self._delete_lookup_rule(selector, self.BLOCK_TABLE_NAME, ipv6=ipv6)

    def _delete_lookup_rule(self, selector: list[str], table_name: str, ipv6: bool) -> None:
        cmd = ["ip"]
        if ipv6:
            cmd.append("-6")
        while True:
            res = self._run_command([*cmd, "rule", "del", *selector, "lookup", table_name], suppress_errors=True)
            if res.returncode != 0:
                break
