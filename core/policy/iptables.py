
class IptablesManager:
    CHAIN_NAME = "LEMUX_OUTPUT"


    def __init__(self, run_command) -> None:
        self._run_command = run_command

    def _run_iptables(self, table: str, args: list[str], check: bool = False, suppress_errors: bool = True, ipv6: bool = False):
        binary = "ip6tables" if ipv6 else "iptables"
        cmd = [binary, "-t", table] + args
        return self._run_command(cmd, check=check, suppress_errors=suppress_errors)

    def _chain_exists(self, table: str, chain: str, ipv6: bool) -> bool:
        # iptables -t table -L chain -n
        res = self._run_iptables(table, ["-L", chain, "-n"], ipv6=ipv6)
        return res.returncode == 0

    def _create_chain(self, table: str, chain: str, ipv6: bool) -> None:
        if not self._chain_exists(table, chain, ipv6):
            self._run_iptables(table, ["-N", chain], check=False, ipv6=ipv6)

    def _rule_exists(self, table: str, chain: str, rule_args: list[str], ipv6: bool) -> bool:
        res = self._run_iptables(table, ["-C", chain] + rule_args, ipv6=ipv6)
        return res.returncode == 0

    def _ensure_jump_rule(self, table: str, parent_chain: str, target_chain: str, ipv6: bool) -> None:
        rule = ["-j", target_chain]
        while self._rule_exists(table, parent_chain, rule, ipv6):
            self._run_iptables(table, ["-D", parent_chain] + rule, ipv6=ipv6)
        self._run_iptables(table, ["-I", parent_chain, "1"] + rule, ipv6=ipv6)

    def _rule_exists_any(self, table: str, chain: str, rule_args: list[str], ipv6: bool) -> bool:
        return self._rule_exists(table, chain, rule_args, ipv6)

    def _ensure_rule_unique(self, table: str, chain: str, rule_args: list[str], ipv6: bool) -> None:
        # Robust method: Remove rule until gone, then add it.
        if self._rule_exists(table, chain, rule_args, ipv6):
             # First delete all occurrences
             while self._rule_exists(table, chain, rule_args, ipv6):
                 self._run_iptables(table, ["-D", chain] + rule_args, ipv6=ipv6)
        
        self._run_iptables(table, ["-A", chain] + rule_args, ipv6=ipv6)

    def _setup_table(self, table: str, ipv6: bool) -> None:
        self._create_chain(table, self.CHAIN_NAME, ipv6)
        self._ensure_jump_rule(table, "OUTPUT", self.CHAIN_NAME, ipv6)

    def ensure_uid_exclusion(self, uid: int) -> None:
        tables = ["nat", "mangle", "filter"]
        # Rule: -m owner --uid-owner {uid} -j ACCEPT
        rule = ["-m", "owner", "--uid-owner", str(uid), "-j", "ACCEPT"]

        for ipv6 in [False, True]:
            for table in tables:
                self._setup_table(table, ipv6)
                self._ensure_rule_unique(table, self.CHAIN_NAME, rule, ipv6)

    def delete_uid_exclusion(self, uid: int) -> None:
        tables = ["nat", "mangle", "filter"]
        rule = ["-m", "owner", "--uid-owner", str(uid), "-j", "ACCEPT"]
        
        for ipv6 in [False, True]:
            for table in tables:
                if self._chain_exists(table, self.CHAIN_NAME, ipv6):
                    while self._rule_exists(table, self.CHAIN_NAME, rule, ipv6):
                        self._run_iptables(table, ["-D", self.CHAIN_NAME] + rule, ipv6=ipv6)
