import os
import shutil
from typing import Optional, Tuple

from .environment import EnvironmentManager


class AudioManager:
    def __init__(self, run_command, env: EnvironmentManager) -> None:
        self._run_command = run_command
        self._env = env

    def ensure_audio_access(self, app_user: str) -> Tuple[Optional[str], Optional[str]]:
        if not shutil.which("setfacl"):
            return None, None
        invoking_user, invoking_uid = self._env.get_invoking_user()
        runtime_dir = f"/run/user/{invoking_uid}"
        pulse_dir = os.path.join(runtime_dir, "pulse")
        pulse_socket = os.path.join(pulse_dir, "native")
        pipewire_socket = os.path.join(runtime_dir, "pipewire-0")
        pipewire_lock = os.path.join(runtime_dir, "pipewire-0.lock")
        dbus_session_socket = os.path.join(runtime_dir, "bus")
        bluetooth_dir = "/run/bluetooth"

        # Minimal traverse ACL to reach host-user audio sockets.
        # Do not set runtime_dir mask/default ACL here.
        if os.path.isdir(runtime_dir):
            self._run_command(["setfacl", "-m", f"u:{app_user}:r-x", runtime_dir])

        # Pulse dir can carry default ACLs so recreated sockets inherit access.
        if os.path.isdir(pulse_dir):
            self._run_command(["setfacl", "-m", f"u:{app_user}:rwX", pulse_dir])
            self._run_command(["setfacl", "-m", "m:rwX", pulse_dir])
            self._run_command(["setfacl", "-m", f"d:u:{app_user}:rwX", pulse_dir])
            self._run_command(["setfacl", "-m", "d:m:rwX", pulse_dir])

        # Set ACLs on audio sockets (PulseAudio, PipeWire, and session D-Bus).
        # D-Bus session socket is needed for Bluetooth audio to work with BlueZ.
        for path in (pulse_socket, pipewire_socket, pipewire_lock, dbus_session_socket):
            if os.path.exists(path):
                self._run_command(["setfacl", "-m", f"u:{app_user}:rw", path])
                self._run_command(["setfacl", "-m", "m:rw", path])

        # Bluetooth audio requires access to BlueZ control socket.
        # BlueZ registers with the system D-Bus and exposes audio devices via BlueZ API.
        # The app needs traverse access to /run/bluetooth to allow PipeWire/PulseAudio
        # to communicate with BlueZ when playing audio to Bluetooth devices.
        if os.path.isdir(bluetooth_dir):
            self._run_command(["setfacl", "-m", f"u:{app_user}:r-x", bluetooth_dir])

        pulse_server = f"unix:{pulse_socket}" if os.path.exists(pulse_socket) else None
        pipewire_remote = f"unix:{pipewire_socket}" if os.path.exists(pipewire_socket) else None
        return pulse_server, pipewire_remote
