import json
import os
import fcntl
from typing import Any, Dict

class StateManager:
    def __init__(self, run_command, env_manager) -> None:
        self._run_command = run_command
        self._env = env_manager

    def _ensure_state_dir(self) -> None:
        state_dir = self._env.state_dir()
        os.makedirs(state_dir, exist_ok=True)
        invoking_user, _invoking_uid = self._env.get_invoking_user()
        try:
            self._run_command(["chown", f"{invoking_user}:{invoking_user}", state_dir])
        except Exception:
            pass

    def load_state(self) -> Dict[str, Any]:
        self._ensure_state_dir()
        state_path = self._env.state_path()
        if not os.path.exists(state_path):
            return {"interfaces": {}, "apps": {}}
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                try:
                    state = json.load(f)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except Exception:
             # Return empty state on failure (e.g. empty file)
             return {"interfaces": {}, "apps": {}}
        return state

    def save_state(self, state: Dict[str, Any]) -> None:
        self._ensure_state_dir()
        state_path = self._env.state_path()
        with open(state_path, "w", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                json.dump(state, f, indent=2, sort_keys=True)
                f.flush()
                # Use fileno for fsync
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
