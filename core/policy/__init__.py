import os
import subprocess
from typing import Any, Dict, List, Optional
from .environment import EnvironmentManager
from .acl import AclManager
from .audio import AudioManager
from .rules import NftRuleManager
from .routing import RoutingManager
from .apps import AppManager
from .trace import TraceManager

NFT_TABLE = "lemux"
NFT_CHAIN = "output"
BASE_TABLE_ID = 100
BASE_PRIORITY = 1000


def _run_command(cmd: List[str], check: bool = False, suppress_errors: bool = False) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    path = env.get("PATH", "")
    if "/usr/sbin" not in path:
        path = f"{path}:/usr/sbin"
    if "/sbin" not in path:
        path = f"{path}:/sbin"
    env["PATH"] = path
    
    if suppress_errors:
        check = False
        
    try:
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=check, env=env)
    except subprocess.CalledProcessError as e:
        if suppress_errors:
            # We must return a CompletedProcess-like object or the actual exception object if possible,
            # but subprocess.run raises it.
            # However, if we set check=False above, it won't raise CalledProcessError.
            # So this except block is only reachable if suppress_errors was False originally but check was True.
            pass
        raise e


_ENV = EnvironmentManager()
_ACL = AclManager(_run_command, _ENV)
_AUDIO = AudioManager(_run_command, _ENV)
_NFT = NftRuleManager(_run_command, NFT_TABLE, NFT_CHAIN)
_ROUTING = RoutingManager(_run_command)
_APPS = AppManager(_run_command, _ENV, _ACL, _AUDIO, _NFT, _ROUTING, BASE_TABLE_ID, BASE_PRIORITY)
_TRACE = TraceManager(_NFT)


def run_nft_trace_test(uid: int, mark: str, test_cmd: Optional[List[str]] = None, timeout_sec: int = 5) -> str:
    return _TRACE.run_nft_trace_test(uid, mark, test_cmd=test_cmd, timeout_sec=timeout_sec)


def normalize_command(command: str) -> str:
    return _APPS.normalize_command(command)


def list_assignments() -> Dict[str, Any]:
    return _APPS.list_assignments()


def assign_app(
    app_command: str,
    iface: str,
    use_profile: Optional[bool] = None,
    existing_user: Optional[str] = None,
) -> Dict[str, Any]:
    return _APPS.assign_app(app_command, iface, use_profile=use_profile, existing_user=existing_user)


def deassign_app(app_command: str) -> None:
    _APPS.deassign_app(app_command)


def reset_all() -> None:
    _APPS.reset_all()


def launch_app(app_command: str, app_entry: Dict[str, Any]) -> None:
    _APPS.launch_app(app_command, app_entry)


def stop_app(app_command: str) -> None:
    _APPS.stop_app(app_command)


def build_command(app_entry: Dict[str, Any]) -> str:
    return _APPS.build_command(app_entry)
