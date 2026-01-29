#!/usr/bin/env python3
import os
import sys

# Ensure we can import from core
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from core.desktop import DesktopManager

def main():
    if os.geteuid() != 0:
        print("[!] This script should likely be run as root (or the user who owns the lemux config) to update files correctly.")
        # We don't enforce it, but warn. lemux usually runs as root?
        # The user runs 'pkexec ... cli.py'. 
        # But 'config.json' might be in /etc/lemux or /home/user/.config/lemux?
        # The core.config handles HOME detection. 
        # If run as root via pkexec, HOME might be /root or preserved.
        # Let's rely on standard core.config behavior.
    
    print("Initializing DesktopManager...")
    dm = DesktopManager()
    
    entries = dm.list_desktop_entries()
    if not entries:
        print("No desktop entries found to upgrade.")
        return

    print(f"Found {len(entries)} desktop entries. Updating...")
    
    success_count = 0
    fail_count = 0
    
    for app_command, path in entries.items():
        print(f"Processing '{app_command}' -> {path} ... ", end="")
        try:
            # create_desktop_entry will regenerate the file content 
            # using the new logic in core/desktop.py
            new_path = dm.create_desktop_entry(app_command)
            if new_path == path:
                 print("[OK]")
            else:
                 print(f"[OK] (Path changed to {new_path})")
            success_count += 1
        except Exception as e:
            print(f"[FAILED] {e}")
            fail_count += 1
            
    print("-" * 40)
    print(f"Upgrade complete. Success: {success_count}, Failed: {fail_count}")

if __name__ == "__main__":
    main()
