import shutil

from .environment import EnvironmentManager


class AclManager:
    def __init__(self, run_command, env: EnvironmentManager) -> None:
        self._run_command = run_command
        self._env = env

    def ensure_shared_access(self, path: str, owner: str) -> None:
        invoking_user, _ = self._env.get_invoking_user()
        try:
            self._run_command(["chown", "-R", f"{owner}:{owner}", path])
            self._run_command(["chmod", "750", path])
        except Exception:
            return

        if shutil.which("setfacl"):
            self._run_command(["setfacl", "-m", f"u:{invoking_user}:rwx,d:u:{invoking_user}:rwx", path])
