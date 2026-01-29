import os
import pwd
from typing import Tuple


class EnvironmentManager:
    def get_invoking_user(self) -> Tuple[str, int]:
        sudo_user = os.environ.get("SUDO_USER")
        if sudo_user:
            pw = pwd.getpwnam(sudo_user)
            return sudo_user, pw.pw_uid
        pkexec_uid = os.environ.get("PKEXEC_UID")
        if pkexec_uid:
            pw = pwd.getpwuid(int(pkexec_uid))
            return pw.pw_name, pw.pw_uid
        current = pwd.getpwuid(os.getuid())
        return current.pw_name, current.pw_uid

    def get_invoking_home(self) -> str:
        user, _ = self.get_invoking_user()
        return pwd.getpwnam(user).pw_dir

    def state_dir(self) -> str:
        return os.path.join(self.get_invoking_home(), ".config", ".lemux")

    def state_path(self) -> str:
        return os.path.join(self.state_dir(), "state.json")

    def app_home_dir(self, username: str) -> str:
        return os.path.join("/home", username)
