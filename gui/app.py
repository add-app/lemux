import sys
sys.dont_write_bytecode = True
import os
import subprocess
import tkinter as tk
from tkinter import ttk
from tkinter import messagebox, filedialog
import shlex
import shutil
import hashlib
import pwd
from typing import Optional
from PIL import Image, ImageTk

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import core.interface as interface
from core import policy
from core import config
from core.logger import logger
from core.icon_manager import IconManager
from core.desktop import DesktopManager


class LemuxApp:
    def __init__(self) -> None:
        self.interface_names = []
        self._icon_manager = IconManager(config.get_home_dir())
        self._desktop_manager = DesktopManager()
        self._status_icon_cache = {}
        self._bootstrap_privileges()

        self.root = tk.Tk()
        self.root.title("Lemux - Soft Network Tunneling")
        self.root.geometry("860x620")

        self._configure_styles()
        self._build_layout()
        self.status_tree.bind("<<TreeviewSelect>>", self.on_status_select)

        self.root.update_idletasks()
        self.root.minsize(self.root.winfo_reqwidth(), self.root.winfo_reqheight())

        self.on_debug_toggle()
        self.on_profile_toggle()
        self.refresh()
        self.load_existing_assignments()
        self.refresh_status()
        self.status_tree.bind("<Button-1>", self.on_status_click)
        self.status_tree.bind("<Double-1>", self.on_status_double_click)
        self.root.bind("<Button-1>", self.on_global_click, add=True)

    def _bootstrap_privileges(self) -> None:
        display = os.environ.get("DISPLAY", ":0")
        xauth_path = os.environ.get("XAUTHORITY")
        if not xauth_path:
            xauth_path = os.path.expanduser("~/.Xauthority")
            if os.getenv("SUDO_USER"):
                xauth_path = f"/home/{os.getenv('SUDO_USER')}/.Xauthority"

        os.environ["DISPLAY"] = display
        os.environ["XAUTHORITY"] = xauth_path

        if os.environ.get("DISPLAY"):
            subprocess.run("xhost +SI:localuser:root", shell=True, capture_output=True, text=True)

        if os.geteuid() != 0:
            script_path = os.path.abspath(__file__)
            os.environ["LEMUX_INVOKING_USER"] = pwd.getpwuid(os.getuid()).pw_name
            python_exec = config.get_python_executable()
            venv_path = os.environ.get("VIRTUAL_ENV")
            path_env = os.environ.get("PATH")
            env_args = [
                f"DISPLAY={display}",
                f"XAUTHORITY={xauth_path}",
                f"LEMUX_INVOKING_USER={os.environ['LEMUX_INVOKING_USER']}",
            ]
            if venv_path:
                env_args.append(f"VIRTUAL_ENV={venv_path}")
            if path_env:
                env_args.append(f"PATH={path_env}")
            try:
                os.execvp(
                    "pkexec",
                    ["pkexec", "env", *env_args, python_exec, script_path],
                )
            except Exception as exc:
                print(f"[X] Failed to elevate with pkexec: {exc}")
                sys.exit(1)

    def _configure_styles(self) -> None:
        self.bg_color = "#f4f2ef"
        self.fg_color = "#3b3a39"
        self.entry_bg = "#ffffff"
        self.button_bg = "#e7e2dc"
        self.button_fg = "#3b3a39"
        self.listbox_bg = "#ffffff"
        self.listbox_fg = "#3b3a39"
        self.border_color = "#d6cfc7"
        self.highlight_bg = "#c8d7e6"
        self.title_color = "#6c8ea3"

        style = ttk.Style()
        style.configure("Soft.TFrame", background=self.bg_color)
        style.configure("Soft.TLabel", background=self.bg_color, foreground=self.fg_color)
        style.configure("Soft.TButton", background=self.button_bg, foreground=self.button_fg, borderwidth=0)
        style.configure("Soft.TLabelframe", background=self.bg_color, foreground=self.fg_color)
        style.configure("Soft.TLabelframe.Label", background=self.bg_color, foreground=self.fg_color)
        style.configure("Soft.TEntry", fieldbackground=self.entry_bg, foreground=self.fg_color)
        style.configure("Soft.TCombobox", fieldbackground=self.entry_bg, background=self.button_bg, foreground=self.fg_color, arrowcolor=self.fg_color)
        style.configure("Soft.Treeview", background=self.listbox_bg, fieldbackground=self.listbox_bg, foreground=self.listbox_fg, bordercolor=self.border_color, indent=0)
        style.configure("Soft.Treeview.Heading", background=self.button_bg, foreground=self.fg_color)
        style.map("Soft.Treeview", background=[("selected", self.highlight_bg)], foreground=[("selected", "#2a2a2a")])
        style.configure("Soft.TCheckbutton", background=self.bg_color, foreground=self.fg_color)
        style.configure("SoftStart.TButton", background="#d8efe2", foreground="#2d6a4f")
        style.configure("SoftStop.TButton", background="#f3d6d2", foreground="#8f2d24")
        style.configure("SoftDesktop.TButton", background="#f6e1c9", foreground="#8a4b1f")
        style.configure("SoftOn.TCheckbutton", background=self.bg_color, foreground=self.title_color)

    def _build_layout(self) -> None:
        self.root.configure(bg=self.bg_color)

        self.main_frame = ttk.Frame(self.root, padding="24", style="Soft.TFrame")
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self.title_frame = ttk.Frame(self.main_frame, style="Soft.TFrame")
        self.title_frame.pack(fill=tk.X, pady=(0, 20))
        self.title_label = ttk.Label(
            self.title_frame,
            text="Lemux - App Tunneling",
            font=("Noto Sans", 16, "bold"),
            style="Soft.TLabel",
            foreground=self.title_color,
        )
        self.title_label.pack(side=tk.LEFT)
        self.debug_var = tk.BooleanVar(value=config.get_config().get("debug", False))
        self.debug_toggle = ttk.Checkbutton(
            self.title_frame,
            text="Debug",
            variable=self.debug_var,
            style="Soft.TCheckbutton",
            command=self.on_debug_toggle,
        )
        self.debug_toggle.pack(side=tk.RIGHT, padx=(0, 10))

        self.profile_var = tk.BooleanVar(value=False)
        self.profile_toggle = ttk.Checkbutton(
            self.title_frame,
            text="Browser Profile",
            variable=self.profile_var,
            style="Soft.TCheckbutton",
            command=self.on_profile_toggle,
        )
        self.profile_toggle.pack(side=tk.RIGHT, padx=(0, 10))

        self.interface_frame = ttk.Frame(self.main_frame, style="Soft.TFrame")
        self.interface_frame.pack(fill=tk.X, pady=(0, 10))
        self.interface_label = ttk.Label(
            self.interface_frame,
            text="Select Interface",
            width=20,
            style="Soft.TLabel",
            font=("Noto Sans", 10),
        )
        self.interface_label.pack(side=tk.LEFT)

        interfaces = interface.get_active_interfaces()
        self.interface_names = [i['name'] for i in interfaces if i['flag'] == 'UP' and i['ip_addresses']]

        self.interface_combo = ttk.Combobox(
            self.interface_frame,
            values=self.interface_names,
            style="Soft.TCombobox",
            state="readonly",
        )
        self.interface_combo.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.refresh_btn = ttk.Button(
            self.interface_frame,
            text="↻",
            width=3,
            command=self.refresh,
            style="Soft.TButton",
        )
        self.refresh_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.user_label = ttk.Label(
            self.interface_frame,
            text="User",
            width=10,
            style="Soft.TLabel",
            font=("Noto Sans", 10),
        )
        self.user_label.pack(side=tk.LEFT, padx=(16, 0))
        self.user_var = tk.StringVar(value="Auto")
        self.user_combo = ttk.Combobox(
            self.interface_frame,
            textvariable=self.user_var,
            values=["Auto"],
            style="Soft.TCombobox",
            state="readonly",
        )
        self.user_combo.pack(side=tk.LEFT, fill=tk.X, expand=False)
        self.user_combo.bind("<<ComboboxSelected>>", lambda _event: self.on_user_selected())

        self.path_frame = ttk.Frame(self.main_frame, style="Soft.TFrame")
        self.path_frame.pack(fill=tk.X, pady=(0, 10))
        self.path_label = ttk.Label(
            self.path_frame,
            text="Application Path",
            width=20,
            style="Soft.TLabel",
            font=("Noto Sans", 10),
        )
        self.path_label.pack(side=tk.LEFT)
        self.path_entry = ttk.Entry(self.path_frame, style="Soft.TEntry")
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.browse_btn = ttk.Button(
            self.path_frame,
            text="Browse",
            width=10,
            command=self.browse_app,
            style="Soft.TButton",
        )
        self.browse_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.add_frame = ttk.Frame(self.main_frame, style="Soft.TFrame")
        self.add_frame.pack(fill=tk.X, pady=(0, 20))
        self.add_btn = ttk.Button(
            self.add_frame,
            text="Add to Queue",
            width=15,
            command=self.add_path,
            style="Soft.TButton",
        )
        self.add_btn.pack(anchor=tk.CENTER)

        self.paths_frame = ttk.Frame(self.main_frame, style="Soft.TFrame")
        self.paths_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 20))

        self.selected_frame = ttk.LabelFrame(self.paths_frame, text="Selected paths", style="Soft.TLabelframe", padding=10)
        self.selected_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        self.selected_paths = tk.Listbox(
            self.selected_frame,
            bg=self.listbox_bg,
            fg=self.listbox_fg,
            selectmode=tk.SINGLE,
            borderwidth=1,
            highlightthickness=1,
            highlightbackground=self.border_color,
            selectbackground=self.highlight_bg,
            selectforeground="#2a2a2a",
            relief=tk.FLAT,
            font=("Noto Sans", 10),
        )
        self.selected_paths.pack(fill=tk.BOTH, expand=True)

        self.created_frame = ttk.LabelFrame(self.paths_frame, text="Created paths", style="Soft.TLabelframe", padding=10)
        self.created_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.created_paths = tk.Listbox(
            self.created_frame,
            bg=self.listbox_bg,
            fg=self.listbox_fg,
            selectmode=tk.SINGLE,
            borderwidth=1,
            highlightthickness=1,
            highlightbackground=self.border_color,
            selectbackground=self.highlight_bg,
            selectforeground="#2a2a2a",
            relief=tk.FLAT,
            font=("Noto Sans", 10),
        )
        self.created_paths.pack(fill=tk.BOTH, expand=True)

        self.bottom_frame = ttk.Frame(self.main_frame, style="Soft.TFrame")
        self.bottom_frame.pack(fill=tk.X, pady=(0, 20))

        self.buttons_frame = ttk.Frame(self.bottom_frame, style="Soft.TFrame")
        self.buttons_frame.pack(anchor=tk.CENTER)

        self.assign_btn = ttk.Button(
            self.buttons_frame,
            text="Assign",
            width=20,
            command=self.assign,
            style="Soft.TButton",
        )
        self.assign_btn.pack(side=tk.LEFT, padx=5)

        self.deassign_btn = ttk.Button(
            self.buttons_frame,
            text="Deassign",
            width=20,
            command=self.deassign_selected,
            style="Soft.TButton",
        )
        self.deassign_btn.pack(side=tk.LEFT, padx=5)
        self.clear_btn = ttk.Button(
            self.buttons_frame,
            text="Deassign All",
            width=20,
            command=self.clear_all_assignments,
            style="Soft.TButton",
        )
        self.clear_btn.pack(side=tk.LEFT, padx=5)

        self.reset_btn = ttk.Button(
            self.buttons_frame,
            text="Reset All Rules",
            width=20,
            command=self.reset_all,
            style="Soft.TButton",
        )
        self.reset_btn.pack(side=tk.LEFT, padx=5)

        self.status_frame = ttk.LabelFrame(self.main_frame, text="Status", style="Soft.TLabelframe", padding=10)
        self.status_frame.pack(fill=tk.BOTH, expand=False, pady=(0, 20))

        status_columns = ("app", "iface", "user", "mark", "table", "rule")
        self.status_tree = ttk.Treeview(self.status_frame, columns=status_columns, show="tree headings", height=5, style="Soft.Treeview")
        self.status_tree.heading("#0", text="")
        self.status_tree.heading("app", text="Application")
        self.status_tree.heading("iface", text="Interface")
        self.status_tree.heading("user", text="User")
        self.status_tree.heading("mark", text="Mark")
        self.status_tree.heading("table", text="Table")
        self.status_tree.heading("rule", text="Priority")
        self.status_tree.column("#0", width=40, minwidth=40, anchor="w", stretch=False)
        self.status_tree.column("app", width=380, anchor="w")
        self.status_tree.column("iface", width=90, anchor="center")
        self.status_tree.column("user", width=110, anchor="center")
        self.status_tree.column("mark", width=80, anchor="center")
        self.status_tree.column("table", width=140, anchor="center")
        self.status_tree.column("rule", width=200, anchor="w")
        self.status_tree.pack(fill=tk.BOTH, expand=True)

        self.bottom_frame = ttk.Frame(self.main_frame, style="Soft.TFrame")
        self.bottom_frame.pack(fill=tk.X)

        self.bottom_buttons_frame = ttk.Frame(self.bottom_frame, style="Soft.TFrame")
        self.bottom_buttons_frame.pack(anchor=tk.CENTER)

        self.start_btn = ttk.Button(
            self.bottom_buttons_frame,
            text="Start",
            width=12,
            command=self.start_selected_app,
            style="SoftStart.TButton",
            state=tk.DISABLED,
        )
        self.start_btn.pack(side=tk.LEFT, padx=6)

        self.stop_btn = ttk.Button(
            self.bottom_buttons_frame,
            text="Stop",
            width=12,
            command=self.stop_selected_app,
            style="SoftStop.TButton",
            state=tk.DISABLED,
        )
        self.stop_btn.pack(side=tk.LEFT, padx=6)

        self.desktop_btn = ttk.Button(
            self.bottom_buttons_frame,
            text="Desktop",
            width=14,
            command=self.toggle_desktop_entry,
            style="SoftDesktop.TButton",
            state=tk.DISABLED,
        )
        self.desktop_btn.pack(side=tk.LEFT, padx=6)

    def _format_queue_item(self, app: str, iface: str, use_profile: bool) -> str:
        tags = []
        if use_profile:
            tags.append("profile")
        suffix = f" [{' '.join(tags)}]" if tags else ""
        return f"{app} -> {iface}{suffix}"

    def _parse_queue_item(self, item: str) -> tuple[str, str, bool]:
        parts = item.split(" [")
        core = parts[0]
        tags = []
        if len(parts) > 1:
            tags = parts[1].rstrip("]").split()
        use_profile = "profile" in tags
        app, iface = core.split(" -> ")
        return app, iface, use_profile

    def refresh(self) -> None:
        interfaces = interface.get_active_interfaces()
        self.interface_names = [i['name'] for i in interfaces if i['flag'] == 'UP' and i['ip_addresses']]
        self.interface_combo['values'] = self.interface_names
        if not self.interface_names:
            self.interface_combo.set("No active interfaces found")
        else:
            self.interface_combo.set(self.interface_names[0])
        self.refresh_users()
        self.refresh_status()

    def refresh_users(self) -> None:
        config.prune_users()
        cfg = config.get_config()
        saved_users = cfg.get("users", [])
        state_users = []
        state = policy.list_assignments()
        for entry in state.get("apps", {}).values():
            user = entry.get("user")
            if user and user.startswith("lemux_"):
                state_users.append(user)
        users = ["Auto"] + sorted({user for user in (*saved_users, *state_users) if user.startswith("lemux_")})
        self.user_combo["values"] = users
        selected = cfg.get("selected_user") or "Auto"
        if selected not in users:
            selected = "Auto"
        self.user_combo.set(selected)

    def on_user_selected(self) -> None:
        selected = self.user_combo.get()
        config.set_selected_user(selected)

    def browse_app(self) -> None:
        selected = filedialog.askopenfilename()
        if selected:
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, selected)

    def add_path(self) -> None:
        app = self.path_entry.get().strip()
        iface = self.interface_combo.get().strip()
        if not app or not iface:
            messagebox.showerror("Error", "Please enter an application path and select an interface.")
            return
        try:
            parts = shlex.split(app)
        except ValueError:
            messagebox.showerror("Error", "Invalid application command.")
            return
        if not parts:
            messagebox.showerror("Error", "Application path not found.")
            return
        if not os.path.exists(parts[0]):
            resolved = shutil.which(parts[0])
            if not resolved:
                messagebox.showerror("Error", "Application path not found.")
                return

        self.selected_paths.insert(tk.END, self._format_queue_item(app, iface, self.profile_var.get()))
        self.path_entry.delete(0, tk.END)

    def assign(self) -> None:
        app_interface = self.selected_paths.get(first=0, last=tk.END)
        if not app_interface:
            messagebox.showinfo("Info", "No paths selected to assign.")
            return

        app_list = []
        for item in app_interface:
            app, iface, use_profile = self._parse_queue_item(item)
            app_list.append((app, iface, use_profile))

        for app, iface, use_profile in app_list:
            try:
                selected_user = self.user_combo.get().strip()
                existing_user = selected_user if selected_user and selected_user != "Auto" else None
                app_entry = policy.assign_app(
                    app,
                    iface,
                    use_profile=use_profile,
                    existing_user=existing_user,
                )
                self.created_paths.insert(tk.END, self._format_queue_item(app, iface, use_profile))
            except Exception as e:
                messagebox.showerror("Error", f"Failed to assign '{app}': {e}")

        self.selected_paths.delete(0, tk.END)
        self.refresh_status()

    def deassign_selected(self) -> None:
        selection = self.created_paths.curselection()
        if not selection:
            messagebox.showinfo("Info", "Select a created path to deassign.")
            return
        item = self.created_paths.get(selection[0])
        app, _iface, _use_profile = self._parse_queue_item(item)
        try:
            policy.deassign_app(app)
            self.created_paths.delete(selection[0])
        except Exception as e:
            messagebox.showerror("Error", f"Failed to deassign '{app}': {e}")
        self.refresh_status()

    def clear_all_assignments(self) -> None:
        if not self.created_paths.size():
            messagebox.showinfo("Info", "No assigned paths to clear.")
            return
        if messagebox.askyesno("Confirm", "Clear all assigned paths and routing rules?"):
            for item in list(self.created_paths.get(first=0, last=tk.END)):
                app, _iface, _use_profile = self._parse_queue_item(item)
                try:
                    policy.deassign_app(app)
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to deassign '{app}': {e}")
            self.created_paths.delete(0, tk.END)
            self.refresh_status()

    def reset_all(self) -> None:
        if messagebox.askyesno("Confirm", "This will remove all Lemux routing rules. Proceed?"):
            try:
                policy.reset_all()
                self.selected_paths.delete(0, tk.END)
                self.created_paths.delete(0, tk.END)
                messagebox.showinfo("Success", "Lemux settings were reset.")
                self.refresh()
            except Exception as e:
                messagebox.showerror("Error", f"An error occurred during reset: {e}")

    def on_debug_toggle(self) -> None:
        config.set_debug(self.debug_var.get())
        if self.debug_var.get():
            os.environ["LEMUX_DEBUG"] = "1"
        else:
            os.environ.pop("LEMUX_DEBUG", None)
        if self.debug_var.get():
            self.debug_toggle.configure(style="SoftOn.TCheckbutton", text="Debug ✓")
        else:
            self.debug_toggle.configure(style="Soft.TCheckbutton", text="Debug")

    def on_profile_toggle(self) -> None:
        if self.profile_var.get():
            self.profile_toggle.configure(style="SoftOn.TCheckbutton", text="Browser Profile ✓")
        else:
            self.profile_toggle.configure(style="Soft.TCheckbutton", text="Browser Profile")

    def load_existing_assignments(self) -> None:
        state = policy.list_assignments()
        for app, app_entry in state.get("apps", {}).items():
            self.created_paths.insert(
                tk.END,
                self._format_queue_item(
                    app,
                    app_entry["iface"],
                    app_entry.get("use_profile", False),
                ),
            )

    def refresh_status(self) -> None:
        self._dismiss_editor()
        for row in self.status_tree.get_children():
            self.status_tree.delete(row)
        self._status_icon_cache = {}
        state = policy.list_assignments()
        for app, app_entry in state.get("apps", {}).items():
            icon = self._icon_manager.get_app_icon(app)
            if icon:
                icon = self._center_icon(icon, int(self.status_tree.column("#0", "width")))
            iface = app_entry.get("iface", "-")
            iface_entry = state.get("interfaces", {}).get(iface, {})
            mark = iface_entry.get("mark", "-")
            table_name = iface_entry.get("table_name", "-")
            priority = iface_entry.get("priority")
            rule = "-"
            if priority is not None:
                rule = str(priority)
            row_id = f"app_{hashlib.sha256(app.encode('utf-8')).hexdigest()[:12]}"
            if icon:
                self._status_icon_cache[row_id] = icon
                self.status_tree.insert("", "end", row_id, text="", image=icon)
            else:
                self.status_tree.insert("", "end", row_id, text="")
            self.status_tree.set(row_id, "app", app)
            self.status_tree.set(row_id, "iface", iface)
            self.status_tree.set(row_id, "user", app_entry.get("user", "-"))
            self.status_tree.set(row_id, "mark", mark)
            self.status_tree.set(row_id, "table", table_name)
            self.status_tree.set(row_id, "rule", rule)
        self.on_status_select()

    def _center_icon(self, icon: tk.PhotoImage, column_width: int) -> tk.PhotoImage:
        try:
            base_img = ImageTk.getimage(icon).convert("RGBA")
        except Exception:
            return icon
        width = max(1, int(column_width))
        height = base_img.height
        left_pad = 4
        if base_img.width > width:
            scale = (width - left_pad) / base_img.width if width > left_pad else 1
            new_size = (max(1, int(base_img.width * scale)), max(1, int(base_img.height * scale)))
            base_img = base_img.resize(new_size, Image.LANCZOS)
            height = base_img.height
        if width <= left_pad + base_img.width:
            canvas = Image.new("RGBA", (max(width, left_pad + base_img.width), height), (0, 0, 0, 0))
            canvas.paste(base_img, (left_pad, 0), base_img)
            return ImageTk.PhotoImage(canvas)
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        canvas.paste(base_img, (left_pad, 0), base_img)
        return ImageTk.PhotoImage(canvas)

    def on_status_select(self, _event=None) -> None:
        app = self._get_selected_app()
        state = tk.NORMAL if app else tk.DISABLED
        self.start_btn.configure(state=state)
        self.stop_btn.configure(state=state)
        if not app:
            self.desktop_btn.configure(state=tk.DISABLED, text="Desktop")
            return
        path = self._desktop_manager.get_desktop_entry(app)
        if path and not os.path.exists(path):
            path = self._desktop_manager.ensure_desktop_entry(app)
        if path and os.path.exists(path):
            self.desktop_btn.configure(state=tk.NORMAL, text="[X] Desktop")
        else:
            self.desktop_btn.configure(state=tk.NORMAL, text="Desktop")

    def _get_selected_app(self) -> Optional[str]:
        selected = self.status_tree.selection()
        if not selected:
            return None
        row_id = selected[0]
        values = self.status_tree.item(row_id, "values")
        if not values:
            return None
        return values[0]

    def start_selected_app(self) -> None:
        app = self._get_selected_app()
        if not app:
            return
        state = policy.list_assignments()
        app_entry = state.get("apps", {}).get(app)
        if not app_entry:
            messagebox.showerror("Error", f"No assignment found for '{app}'.")
            return
        try:
            command = policy.build_command(app_entry) or app
            logger.info(f"launch_app requested from status button: {command}")
            policy.launch_app(command, app_entry)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to launch '{app}': {e}")

    def stop_selected_app(self) -> None:
        app = self._get_selected_app()
        if not app:
            return
        try:
            policy.stop_app(app)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to stop '{app}': {e}")

    def toggle_desktop_entry(self) -> None:
        app = self._get_selected_app()
        if not app:
            return
        path = self._desktop_manager.get_desktop_entry(app)
        if path and os.path.exists(path):
            try:
                self._desktop_manager.delete_desktop_entry(app)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to delete desktop entry: {e}")
                return
            self.desktop_btn.configure(text="Desktop")
            return
        try:
            self._desktop_manager.create_desktop_entry(app)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create desktop entry: {e}")
            return
        self.desktop_btn.configure(text="[X] Desktop")

    def on_status_click(self, event) -> None:
        self._dismiss_editor()
        region = self.status_tree.identify("region", event.x, event.y)
        if region not in ("cell", "tree"):
            return
        return

    def on_status_double_click(self, event) -> None:
        region = self.status_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        self.on_status_edit(event)

    def on_status_edit(self, event) -> None:
        region = self.status_tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        self._dismiss_editor()
        col = self.status_tree.identify_column(event.x)
        if col not in ("#1", "#2", "#3"):
            return
        row_id = self.status_tree.identify_row(event.y)
        if not row_id:
            return
        bbox = self.status_tree.bbox(row_id, col)
        if not bbox:
            return
        x, y, width, height = bbox
        values = self.status_tree.item(row_id, "values")
        if len(values) < 6:
            return
        col_index = int(col[1:]) - 1
        current = values[col_index]

        editor = None
        if col == "#2":
            editor = ttk.Combobox(self.status_tree, values=self.interface_names, style="Soft.TCombobox", state="readonly")
        elif col == "#3":
            users = [user for user in self.user_combo["values"] if user != "Auto"]
            editor = ttk.Combobox(self.status_tree, values=users, style="Soft.TCombobox", state="readonly")
        else:
            editor = ttk.Entry(self.status_tree, style="Soft.TEntry")
            editor.insert(0, current)

        editor.place(x=x, y=y, width=width, height=height)
        if isinstance(editor, ttk.Combobox):
            editor.set(current)
        editor.focus_set()

        self._edit_entry = editor
        self._edit_info = (row_id, col, values)

        editor.bind("<Return>", lambda _event: self._commit_status_edit())
        editor.bind("<Escape>", lambda _event: self._cancel_status_edit())
        if isinstance(editor, ttk.Combobox):
            editor.bind("<<ComboboxSelected>>", lambda _event: self._commit_status_edit())
        else:
            editor.bind("<FocusOut>", lambda _event: self._commit_status_edit())

    def on_global_click(self, event) -> None:
        if not getattr(self, "_edit_entry", None):
            return
        self.root.after(120, lambda: self._cancel_if_clicked_outside(event))

    def _cancel_if_clicked_outside(self, event) -> None:
        editor = getattr(self, "_edit_entry", None)
        if not editor:
            return
        widget = getattr(event, "widget", None)
        if widget and (widget is editor or widget.winfo_toplevel() is editor.winfo_toplevel()):
            return
        self._cancel_status_edit()

    def _cancel_status_edit(self) -> None:
        self._dismiss_editor()

    def _dismiss_editor(self) -> None:
        editor = getattr(self, "_edit_entry", None)
        if editor:
            try:
                editor.place_forget()
                editor.destroy()
            except Exception:
                pass
        self._edit_entry = None
        self._edit_info = None

    def _commit_status_edit(self) -> None:
        if not getattr(self, "_edit_entry", None) or not getattr(self, "_edit_info", None):
            return
        entry = self._edit_entry
        row_id, col, values = self._edit_info
        new_value = entry.get().strip()
        entry.destroy()
        self._edit_entry = None
        self._edit_info = None

        if not new_value:
            return
        old_app = values[0]
        old_iface = values[1]
        old_user = values[2]

        new_app = old_app
        new_iface = old_iface
        new_user = old_user

        if col == "#1":
            new_app = new_value
        elif col == "#2":
            new_iface = new_value
        elif col == "#3":
            new_user = new_value

        if new_app == old_app and new_iface == old_iface and new_user == old_user:
            return

        if new_user and not new_user.startswith("lemux_"):
            messagebox.showerror("Error", "Only lemux_* users from configuration can be used.")
            return

        cfg_users = config.get_config().get("users", [])
        if new_user not in ("", "Auto") and new_user not in cfg_users:
            messagebox.showerror("Error", "User is not registered in configuration.")
            return

        if new_iface not in self.interface_names:
            messagebox.showerror("Error", f"Interface not available: {new_iface}")
            return

        state = policy.list_assignments()
        app_entry = state.get("apps", {}).get(old_app)
        if not app_entry:
            messagebox.showerror("Error", f"No assignment found for '{old_app}'.")
            return
        use_profile = app_entry.get("use_profile", False)
        existing_user = new_user if new_user and new_user != "Auto" else None

        try:
            policy.deassign_app(old_app)
            policy.assign_app(new_app, new_iface, use_profile=use_profile, existing_user=existing_user)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update assignment: {e}")
            self.refresh_status()
            return

        for idx in range(self.created_paths.size()):
            item = self.created_paths.get(idx)
            if item.startswith(f"{old_app} ->"):
                self.created_paths.delete(idx)
                self.created_paths.insert(idx, self._format_queue_item(new_app, new_iface, use_profile))
                break

        self.refresh_status()


    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = LemuxApp()
    app.run()


if __name__ == '__main__':
    main()
