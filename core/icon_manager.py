import glob
import io
import os
import shlex
import shutil
import subprocess
from typing import Optional

from core.desktop import list_desktop_files, normalize_for_match

try:
    from PIL import Image, ImageTk
except Exception:
    Image = None
    ImageTk = None

try:
    import cairosvg
except Exception:
    cairosvg = None


class IconManager:
    def __init__(self, home_dir: str) -> None:
        self._icon_cache: dict[str, Optional[object]] = {}
        self._svg_unavailable: set[str] = set()
        self._icon_search_roots = self._build_icon_search_roots(home_dir)
        self._icon_extra_roots = ["/opt", "/usr/share", "/usr/lib", "/usr/lib64"]

    def get_app_icon(self, app_command: str) -> Optional[object]:
        if app_command in self._icon_cache:
            return self._icon_cache[app_command]

        icon_path = self._find_icon_path(app_command)
        if not icon_path:
            self._icon_cache[app_command] = None
            return None

        try:
            ext = os.path.splitext(icon_path)[1].lower()
            if ext == ".svg":
                image = self._load_svg_icon(icon_path)
            else:
                image = ImageTk.PhotoImage(file=icon_path) if ImageTk else None
                if image and image.width() > 20:
                    factor = max(1, image.width() // 20)
                    image = image.subsample(factor, factor)
            self._icon_cache[app_command] = image
            return image
        except Exception:
            self._icon_cache[app_command] = None
            return None

    def _find_icon_path(self, app_command: str) -> Optional[str]:
        app_exec = self._extract_exec_basename(app_command)
        app_full = self._extract_exec_path(app_command)
        app_norm = normalize_for_match(app_command)
        for desktop_path in list_desktop_files():
            exec_name, icon_name, try_exec, wm_class = self._parse_desktop_file(desktop_path)
            if not exec_name or not icon_name:
                continue
            exec_base = self._extract_exec_basename(exec_name)
            exec_full = self._extract_exec_path(exec_name)
            try_base = self._extract_exec_basename(try_exec) if try_exec else ""
            try_full = self._extract_exec_path(try_exec) if try_exec else ""
            exec_norm = normalize_for_match(exec_name)
            try_norm = normalize_for_match(try_exec)
            wm_norm = (wm_class or "").lower()
            if (
                exec_base == app_exec
                or exec_full == app_full
                or try_base == app_exec
                or try_full == app_full
                or (app_norm and exec_norm and exec_norm.startswith(app_norm))
                or (app_norm and exec_norm and app_norm.startswith(exec_norm))
                or (app_norm and try_norm and try_norm.startswith(app_norm))
                or (app_norm and try_norm and app_norm.startswith(try_norm))
                or exec_base in app_command
                or app_exec in exec_name
                or (wm_norm and wm_norm in app_command.lower())
            ):
                resolved = self._resolve_icon_name(icon_name)
                if resolved:
                    return resolved
        return None

    def _parse_desktop_file(self, path: str) -> tuple[str, str, str, str]:
        exec_name = ""
        icon_name = ""
        try_exec = ""
        wm_class = ""
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("Exec=") and not exec_name:
                        exec_name = line.split("=", 1)[1].strip()
                    if line.startswith("Icon=") and not icon_name:
                        icon_name = line.split("=", 1)[1].strip()
                    if line.startswith("TryExec=") and not try_exec:
                        try_exec = line.split("=", 1)[1].strip()
                    if line.startswith("StartupWMClass=") and not wm_class:
                        wm_class = line.split("=", 1)[1].strip()
                    if exec_name and icon_name and try_exec and wm_class:
                        break
        except OSError:
            return "", "", "", ""
        return exec_name, icon_name, try_exec, wm_class

    def _extract_exec_basename(self, command: str) -> str:
        try:
            parts = shlex.split(command)
        except ValueError:
            return os.path.basename(command.strip())
        if not parts:
            return ""
        return os.path.basename(parts[0])

    def _extract_exec_path(self, command: str) -> str:
        try:
            parts = shlex.split(command)
        except ValueError:
            parts = [command.strip()]
        if not parts:
            return ""
        candidate = parts[0]
        if os.path.isabs(candidate):
            return os.path.realpath(candidate)
        resolved = shutil.which(candidate)
        return os.path.realpath(resolved) if resolved else ""

    def _resolve_icon_name(self, icon_name: str) -> Optional[str]:
        if os.path.isabs(icon_name) and os.path.exists(icon_name):
            if self._is_supported_icon(icon_name):
                return icon_name
            return None

        # Prepare candidates
        candidates = []
        ext = os.path.splitext(icon_name)[1].lower()
        if ext:
            candidates.append(icon_name)
            if ext == ".svg" and not self._can_render_svg():
                base = os.path.splitext(icon_name)[0]
                candidates.extend([base + ".png", base + ".gif", base + ".xpm"])
        else:
            for extension in (".png", ".svg", ".xpm", ".gif"):
                 candidates.append(icon_name + extension)
            # Add fallback for potential reverse-DNS names (e.g. telegram-desktop -> org.telegram.desktop.png)
            # and other common variations if exact match fails
            if "-" in icon_name:
                 # heuristic: org.telegram.desktop
                 parts = icon_name.split("-")
                 candidates.append(".".join(["org", *parts]) + ".png")
                 candidates.append(".".join(["com", *parts]) + ".png")

        # Prioritize standard directories to avoid scanning everything
        # XDG Icon Theme Spec mostly uses: <base>/<theme>/<size>/<category>/<icon>
        # We simplify to: <base>/<size>/<category>/<icon> (assuming root passed is <base>/<theme> or just <base>)
        
        sizes = [
            "256x256", "192x192", "128x128", "96x96", "72x72", "64x64", 
            "48x48", "32x32", "24x24", "22x22", "16x16", 
            "512", "256", "192", "128", "96", "72", "64", "48", "32", "24", "22", "16",
            "scalable", "symbolic"
        ]
        categories = ["apps", "actions", "devices", "places", "status", "categories", "mimetypes", "panel", "emblems"]

        # Fast path: Check specific paths first
        for base in self._icon_search_roots:
             if not os.path.isdir(base):
                 continue
             
             # 1. Direct check in base (uncommon but possible for pixmaps)
             for candidate in candidates:
                 path = os.path.join(base, candidate)
                 if os.path.isfile(path) and self._is_supported_icon(path):
                     return path
             
             # 2. Check XDG hierarchy without recursion
             for size in sizes:
                 size_dir = os.path.join(base, size)
                 if os.path.isdir(size_dir):
                     for category in categories:
                          cat_dir = os.path.join(size_dir, category)
                          if not os.path.isdir(cat_dir):
                               continue
                          for candidate in candidates:
                               path = os.path.join(cat_dir, candidate)
                               if os.path.isfile(path) and self._is_supported_icon(path):
                                   return path

                 # 3. Check inverted hierarchy (category/size) - common in KDE/?
                 # e.g. /usr/share/icons/breeze-dark/apps/48/yandex-browser.svg
                 # Here 'size' loop is outer, so we check base/size (failed), then iterate categories?
                 # No, if structure is apps/48, then base/apps is the directory.
            
             for category in categories:
                  cat_dir = os.path.join(base, category)
                  if os.path.isdir(cat_dir):
                       for size in sizes:
                           size_dir = os.path.join(cat_dir, size)
                           if not os.path.isdir(size_dir):
                                continue
                           for candidate in candidates:
                                path = os.path.join(size_dir, candidate)
                                if os.path.isfile(path) and self._is_supported_icon(path):
                                    return path

        # Slow path: Walk only if strictly necessary, but limit depth/scope?
        # Actually, scanning all of /usr/share/icons recursively is what caused the performance hit.
        # We will SKIP deep recursion. Most icons should be found in the standard structure above.
        
        # Fallback: Check "hicolor" explicitly if not in roots?
        # The roots logic already adds standard paths.

        # One final check: If icon_name is 'telegram-desktop' but file is 'org.telegram.desktop.png',
        # we might need a looser match if the candidate list didn't catch it.
        # But scanning is expensive. Let's try to be smart.
        # Check standard apps dirs for partial matches?
        
        for base in self._icon_search_roots:
             for size in sizes: # check checks typical app dirs
                  app_dir = os.path.join(base, size, "apps")
                  if os.path.isdir(app_dir):
                       # Try quick list if directory is small-ish
                       try:
                           files = os.listdir(app_dir)
                           # exact match logic was already done.
                           # let's try 'contains' logic only for 'apps' folders
                           lower_name = icon_name.lower().replace("-", ".")
                           for f in files:
                                if lower_name in f.lower() and self._is_supported_icon(os.path.join(app_dir, f)):
                                     return os.path.join(app_dir, f)
                       except OSError:
                           pass

        return None

    def _build_icon_search_roots(self, home_dir: str) -> list[str]:
        theme_dirs = self._get_icon_theme_dirs(home_dir)
        roots = [
            os.path.join(home_dir, ".local", "share", "icons"),
            "/usr/share/icons/hicolor",
            "/usr/share/icons",
            "/usr/share/pixmaps",
        ]
        for item in theme_dirs:
            if item not in roots:
                roots.append(item)
        return roots

    def _get_icon_theme_dirs(self, home_dir: str) -> list[str]:
        dirs = []
        icon_theme = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()
        if "kde" in icon_theme or "plasma" in icon_theme:
            dirs.extend([
                "/usr/share/icons/breeze",
                "/usr/share/icons/breeze-dark",
            ])
        
        # Scan standard icon bases for themes
        bases = ["/usr/share/icons", os.path.join(home_dir, ".local", "share", "icons")]
        for base in bases:
            if os.path.isdir(base):
                for entry in os.listdir(base):
                    if entry.startswith("."):
                        continue
                    path = os.path.join(base, entry)
                    if os.path.isdir(path):
                        dirs.append(path)
        return dirs

    def _is_supported_icon(self, path: str) -> bool:
        ext = os.path.splitext(path)[1].lower()
        if ext in (".png", ".gif", ".xpm"):
            return True
        if ext == ".svg":
            return self._can_render_svg()
        return False

    def _can_render_svg(self) -> bool:
        global Image, ImageTk, cairosvg
        if Image is None or ImageTk is None:
            try:
                from PIL import Image as PILImage, ImageTk as PILImageTk
                Image = PILImage
                ImageTk = PILImageTk
            except Exception:
                Image = None
                ImageTk = None
        if cairosvg is None:
            try:
                import cairosvg as CairoSVG
                cairosvg = CairoSVG
            except Exception:
                cairosvg = None
        if Image is None or ImageTk is None:
            return False
        if cairosvg is not None:
            return True
        return shutil.which("rsvg-convert") is not None

    def _load_svg_icon(self, path: str) -> Optional[object]:
        if not self._can_render_svg():
            return None
        try:
            if cairosvg is not None:
                png_bytes = cairosvg.svg2png(url=path, output_width=20, output_height=20)
            else:
                converter = shutil.which("rsvg-convert")
                if not converter:
                    return None
                result = subprocess.run(
                    [converter, "-w", "20", "-h", "20", "-o", "-", path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                if result.returncode != 0 or not result.stdout:
                    return None
                png_bytes = result.stdout
            image = Image.open(io.BytesIO(png_bytes))
            return ImageTk.PhotoImage(image)
        except Exception:
            return None
