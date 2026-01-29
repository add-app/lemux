
import os
import sys
import time
import subprocess
import argparse
import fcntl
import logging
import shutil

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] ACL-KEEPER: %(message)s')
logger = logging.getLogger(__name__)

class AclKeeper:
    def __init__(self, host_uid: int, app_user: str, interval: int = 5):
        self.host_uid = host_uid
        self.app_user = app_user
        self.interval = interval
        self.runtime_dir = f"/run/user/{host_uid}"
        self.pulse_dir = os.path.join(self.runtime_dir, "pulse")
        self.targets = [
            self.runtime_dir,
            self.pulse_dir,
            os.path.join(self.pulse_dir, "native"),
            os.path.join(self.runtime_dir, "pipewire-0"),
            os.path.join(self.runtime_dir, "pipewire-0.lock"),
        ]

    def check_app_running(self) -> bool:
        # Check if any process is running as app_user using pgrep
        if not shutil.which("pgrep"):
            logger.error("pgrep not found, cannot monitor process.")
            return False 
        try:
            # pgrep -u <user> returns 0 if found, 1 if not
            ret = subprocess.call(
                ["pgrep", "-u", self.app_user], 
                stdout=subprocess.DEVNULL, 
                stderr=subprocess.DEVNULL
            )
            return ret == 0
        except Exception:
            pass
        return False

    def apply_acls(self):
        for path in self.targets:
            if not os.path.exists(path):
                continue
            
            needs_fix = False
            # Quick check via getfacl is expensive? 
            # We can just blindly re-apply? It's "lightweight" enough if 5s interval.
            # But getfacl allows logging "Restored permissions".
            
            # Let's blindly apply to be robust and simple, or check first?
            # Checking first is better for logs.
            
            try:
                # We interpret "rwX" as sufficiently permissive.
                subprocess.run(
                    ["setfacl", "-m", f"u:{self.app_user}:rwX", path],
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                # Ensure mask is correct too
                subprocess.run(
                    ["setfacl", "-m", "m:rwX", path],
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception as e:
                logger.error(f"Failed to apply ACLs on {path}: {e}")

    def run(self):
        logger.info(f"Starting ACL Keeper for {self.app_user} (Host: {self.host_uid})")
        
        lock_file_path = f"/tmp/lemux_acl_keeper_{self.app_user}.lock"
        lock_file = open(lock_file_path, "w")
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError:
            logger.info("Another instance is running. Exiting.")
            return

        try:
            # Initial wait to let app start
            time.sleep(2)
            
            while True:
                if not self.check_app_running():
                    logger.info("No app processes found. Exiting.")
                    break
                
                self.apply_acls()
                time.sleep(self.interval)
                
        finally:
            fcntl.flock(lock_file, fcntl.LOCK_UN)
            lock_file.close()
            if os.path.exists(lock_file_path):
                try:
                    os.remove(lock_file_path)
                except Exception:
                    pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host-uid", type=int, required=True)
    parser.add_argument("--app-user", type=str, required=True)
    parser.add_argument("--interval", type=int, default=5)
    args = parser.parse_args()

    if os.geteuid() != 0:
        print("Must be run as root.")
        sys.exit(1)

    keeper = AclKeeper(args.host_uid, args.app_user, args.interval)
    keeper.run()

if __name__ == "__main__":
    main()
