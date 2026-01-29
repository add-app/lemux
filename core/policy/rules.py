from typing import Optional


class NftRuleManager:
    def __init__(self, run_command, table: str, chain: str) -> None:
        self._run_command = run_command
        self._table = table
        self._chain = chain

    def ensure_table_chain(self) -> None:
        table_list = self._run_command(["nft", "list", "tables"]).stdout
        if f"table inet {self._table}" not in table_list:
            self._run_command(["nft", "add", "table", "inet", self._table])

        chain_list = self._run_command(["nft", "list", "table", "inet", self._table]).stdout
        if f"chain {self._chain}" not in chain_list:
            self._run_command([
                "nft", "add", "chain", "inet", self._table, self._chain,
                "{", "type", "route", "hook", "output", "priority", "mangle", ";", "policy", "accept", ";", "}",
            ])

    def _find_rule_handles(self, selector: str, mark: str) -> list[str]:
        rules = self._run_command(["nft", "-a", "list", "chain", "inet", self._table, self._chain]).stdout
        target_mark = int(mark, 16)
        handles = []
        for line in rules.splitlines():
             if selector in line and "meta mark set" in line and "handle" in line:
                try:
                    # Extract mark part: ... meta mark set 0x... ...
                    parts = line.split("meta mark set")
                    if len(parts) > 1:
                        mark_part = parts[1].strip().split()[0]
                        if int(mark_part, 16) == target_mark:
                            handles.append(line.rsplit("handle", 1)[-1].strip())
                except (ValueError, IndexError):
                    continue
        return handles

    def find_uid_rule_handles(self, uid: int, mark: str) -> list[str]:
        return self._find_rule_handles(f"meta skuid {uid}", mark)

    def ensure_uid_mark(self, uid: int, mark: str) -> Optional[str]:
        self.ensure_table_chain()
        handles = self.find_uid_rule_handles(uid, mark)
        if len(handles) > 1:
            # Duplicate detection: Keep the last one, delete others
            for h in handles[:-1]:
                self._run_command(["nft", "delete", "rule", "inet", self._table, self._chain, "handle", h])
            return handles[-1]
        if handles:
            return handles[0]
            
        self._run_command([
            "nft", "add", "rule", "inet", self._table, self._chain,
            "meta", "skuid", str(uid), "meta", "mark", "set", mark,
        ])
        new_handles = self.find_uid_rule_handles(uid, mark)
        return new_handles[0] if new_handles else None

    def delete_uid_mark(self, uid: int, mark: str) -> None:
        handles = self.find_uid_rule_handles(uid, mark)
        for handle in handles:
            self._run_command(["nft", "delete", "rule", "inet", self._table, self._chain, "handle", handle])

    def find_gid_rule_handles(self, gid: int, mark: str) -> list[str]:
        return self._find_rule_handles(f"meta skgid {gid}", mark)

    def ensure_gid_mark(self, gid: int, mark: str) -> Optional[str]:
        self.ensure_table_chain()
        handles = self.find_gid_rule_handles(gid, mark)
        if len(handles) > 1:
             # Duplicate detection: Keep the last one, delete others
            for h in handles[:-1]:
                self._run_command(["nft", "delete", "rule", "inet", self._table, self._chain, "handle", h])
            return handles[-1]
        if handles:
            return handles[0]

        self._run_command([
            "nft", "add", "rule", "inet", self._table, self._chain,
            "meta", "skgid", str(gid), "meta", "mark", "set", mark,
        ])
        new_handles = self.find_gid_rule_handles(gid, mark)
        return new_handles[0] if new_handles else None

    def delete_gid_mark(self, gid: int, mark: str) -> None:
        handles = self.find_gid_rule_handles(gid, mark)
        for handle in handles:
            self._run_command(["nft", "delete", "rule", "inet", self._table, self._chain, "handle", handle])

    def add_trace_rule(self, uid: int) -> Optional[str]:
        self.ensure_table_chain()
        self._run_command([
            "nft", "add", "rule", "inet", self._table, self._chain,
            "meta", "skuid", str(uid), "meta", "nftrace", "set", "1",
        ])
        rules = self._run_command(["nft", "-a", "list", "chain", "inet", self._table, self._chain]).stdout
        for line in rules.splitlines():
            if f"meta skuid {uid}" in line and "nftrace set 1" in line and "handle" in line:
                return line.rsplit("handle", 1)[-1].strip()
        return None

    def delete_trace_rule(self, handle: Optional[str]) -> None:
        if handle:
            self._run_command(["nft", "delete", "rule", "inet", self._table, self._chain, "handle", handle])
