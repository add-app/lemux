import subprocess
import re
import logging
from typing import List, Dict, Any

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')


class InterfaceManager:
    def __init__(self) -> None:
        pass

    def _run_command(self, command_parts, check_return=True, suppress_errors=False) -> str:
        """
        Helper function to run a shell command and capture its output.

        Args:
            command_parts (list): A list of strings representing the command and its arguments.
                                  E.g., ['ip', '-o', 'link', 'show']
            check_return (bool): If True, raise an exception if the command returns a non-zero exit code.
            suppress_errors (bool): If True, log errors but do not raise an exception.

        Returns:
            str: The standard output of the command.

        Raises:
            subprocess.CalledProcessError: If the command returns a non-zero exit code and check_return is True.
            FileNotFoundError: If the command itself is not found.
        """
        try:
            result = subprocess.run(
                command_parts,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=check_return,
                encoding='utf-8'
            )
            return result.stdout.strip()
        except FileNotFoundError:
            logging.error(f"Command not found: '{' '.join(command_parts)}'. Make sure it's in your PATH.")
            if not suppress_errors:
                raise
        except subprocess.CalledProcessError as e:
            logging.error(f"Command failed: '{' '.join(command_parts)}'")
            logging.error(f"Stderr: {e.stderr.strip()}")
            if not suppress_errors:
                raise
        except Exception as e:
            logging.error(f"An unexpected error occurred while running '{' '.join(command_parts)}': {e}")
            if not suppress_errors:
                raise
        return ""

    def get_system_dns_servers(self) -> List[str]:
        """
        Reads the system's DNS servers from /etc/resolv.conf.
        Note: These are typically system-wide, not per-interface.
        """
        dns_servers = []
        try:
            with open('/etc/resolv.conf', 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('nameserver'):
                        parts = line.split()
                        if len(parts) > 1:
                            ip = parts[1]
                            if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip) or \
                               re.match(r'^([0-9a-fA-F]{1,4}:){1,7}[0-9a-fA-F]{1,4}$', ip):
                                dns_servers.append(ip)
        except FileNotFoundError:
            logging.warning("/etc/resolv.conf not found. Cannot determine DNS servers.")
        except Exception as e:
            logging.error(f"Error reading /etc/resolv.conf: {e}")
        return dns_servers

    def get_interface_dns(self, iface: str) -> List[str]:
        """
        Attempts to retrieve DNS servers specifically associated with the given interface.
        Uses 'nmcli' if available.
        """
        dns_servers = []
        try:
            # Try nmcli
            output = self._run_command(['nmcli', 'dev', 'show', iface], suppress_errors=True)
            if output:
                for line in output.split('\n'):
                    if 'IP4.DNS' in line or 'IP6.DNS' in line:
                        parts = line.split(':')
                        if len(parts) > 1:
                            dns_servers.append(parts[1].strip())
        except Exception:
            pass

        if not dns_servers:
            pass
            
        return dns_servers

    def get_active_interfaces(self) -> List[Dict[str, Any]]:
        """
        Connects to all available internet interfaces (Wi-Fi, LAN, USB, Bluetooth tethering)
        and retrieves detailed information for each active interface on a Linux system.

        Uses 'ip' command-line utility for information gathering.
        """
        interfaces = []
        system_dns = self.get_system_dns_servers()

        ip_link_output = self._run_command(['ip', '-o', 'link', 'show'])
        if not ip_link_output:
            logging.error("Failed to get basic interface link information.")
            return []

        link_lines = ip_link_output.strip().split('\n')

        for line in link_lines:
            parts = line.split(':')
            if len(parts) < 2:
                continue

            name = parts[1].strip().split('@')[0]
            if name == 'lo':
                continue

            interface_info = {
                'name': name,
                'flag': 'DOWN',
                'type': 'Unknown',
                'ip_addresses': [],
                'mac': 'N/A',
                'metric': 'N/A',
                'gateways': [],
                'system_dns': system_dns
            }

            flags_match = re.search(r'<([^>]+)>', line)
            if flags_match:
                flags_str = flags_match.group(1)
                if "UP" in flags_str:
                    interface_info['flag'] = "UP"

            if interface_info['flag'] == "DOWN":
                interfaces.append(interface_info)
                continue

            mac_match = re.search(r'link/ether\s+([0-9a-fA-F:]{17})', line)
            if mac_match:
                interface_info['mac'] = mac_match.group(1).upper()

            if name.startswith("wl"):
                interface_info['type'] = "Wi-Fi"
            elif name.startswith("en") or name.startswith("eth"):
                interface_info['type'] = "Ethernet"
            elif name.startswith("usb"):
                interface_info['type'] = "USB"
            elif name.startswith("bnep") or name.startswith("bt"):
                interface_info['type'] = "Bluetooth Tethering"
            elif name.startswith("veth") or name.startswith("br") or \
                 name.startswith("docker") or name.startswith("tun") or \
                 name.startswith("tap"):
                interface_info['type'] = "Virtual/Bridge/VPN"

            for family in ['inet', 'inet6']:
                ip_addr_output = self._run_command(['ip', '-f', family, 'addr', 'show', name], suppress_errors=True)
                if ip_addr_output:
                    for ip_line in ip_addr_output.split('\n'):
                        ip_match = re.search(r'inet(?:6)?\s+([0-9a-fA-F.:/]+)\s+brd', ip_line)
                        if not ip_match:
                            ip_match = re.search(r'inet(?:6)?\s+([0-9a-fA-F.:/]+)\s+scope', ip_line)
                        if ip_match:
                            interface_info['ip_addresses'].append(ip_match.group(1))

            ip_route_output = self._run_command(['ip', 'route', 'show'], suppress_errors=True)
            if ip_route_output:
                for route_line in ip_route_output.split('\n'):
                    if f"dev {name}" in route_line:
                        metric_match = re.search(r'metric\s+(\d+)', route_line)
                        if metric_match:
                            interface_info['metric'] = int(metric_match.group(1))

                        gateway_match = re.search(r'via\s+([0-9a-fA-F.:]+)', route_line)
                        if gateway_match and gateway_match.group(1) not in interface_info['gateways']:
                            interface_info['gateways'].append(gateway_match.group(1))

            interfaces.append(interface_info)

        return interfaces


_INTERFACES = InterfaceManager()


def _run_command(command_parts, check_return=True, suppress_errors=False):
    return _INTERFACES._run_command(command_parts, check_return=check_return, suppress_errors=suppress_errors)


def get_system_dns_servers():
    return _INTERFACES.get_system_dns_servers()


def get_interface_dns(iface: str):
    return _INTERFACES.get_interface_dns(iface)


def get_active_interfaces():
    return _INTERFACES.get_active_interfaces()

if __name__ == "__main__":
    print("--- Detected Network Interfaces ---")
    active_interfaces = get_active_interfaces()
    if not active_interfaces:
        print("No active network interfaces found or an error occurred.")
    else:
        for iface in active_interfaces:
            print(f"\nInterface: {iface['name']}")
            print(f"  Status: {iface['flag']}")
            print(f"  Type: {iface['type']}")
            print(f"  MAC Address: {iface['mac']}")
            print(f"  IP Addresses: {', '.join(iface['ip_addresses']) if iface['ip_addresses'] else 'N/A'}")
            print(f"  Metric: {iface['metric']}")
            print(f"  Gateways (associated with device routes): {', '.join(iface['gateways']) if iface['gateways'] else 'N/A'}")
            print(f"  System DNS Servers: {', '.join(iface['system_dns']) if iface['system_dns'] else 'N/A'}")

    print("\n--- End of Report ---")
