import subprocess
from typing import List, Optional

from core.logger import logger


class TraceManager:
    def __init__(self, nft) -> None:
        self._nft = nft

    def run_nft_trace_test(
        self,
        uid: int,
        mark: str,
        test_cmd: Optional[List[str]] = None,
        timeout_sec: int = 5,
    ) -> str:
        """
        Adds a temporary nftrace rule for a UID, runs nft monitor trace briefly,
        optionally executes a test command, and then removes the rule.
        """
        handle = self._nft.add_trace_rule(uid)
        if not handle:
            return "Failed to add nft trace rule."

        output = ""
        proc = subprocess.Popen(
            ["nft", "monitor", "trace"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            if test_cmd:
                subprocess.run(test_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            output, _ = proc.communicate(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                output, _ = proc.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                proc.kill()
                output = ""
        finally:
            self._nft.delete_trace_rule(handle)

        logger.debug(f"nft trace output: {output.strip()}")
        return output.strip() or "No nft trace output captured."
