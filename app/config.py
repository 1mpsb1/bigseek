from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

APP_NAME = "BigSeekDesktop"
APP_TITLE = "BigSeek Desktop"
APP_AUTHOR = "1mpsb1"
APP_VERSION_FALLBACK = "1.0.0"
DEFAULT_DOMAIN = "https://chat.deepseek.com/"

# QtWebEngine puts its own token into the UA string; some sites dislike that.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)


def project_dir() -> Path:
    """Folder next to the executable, or the repo root when run from source.

    In a frozen (PyInstaller) build ``__file__`` points inside ``_internal``,
    so the portable flag has to be looked up next to the exe instead.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_root() -> Path:
    """Where settings, sessions and browser profiles live.

    Drop a file named ``portable.flag`` next to the exe (or main.py) to keep
    everything in ``./data`` instead of %LOCALAPPDATA%.
    """
    if (project_dir() / "portable.flag").exists():
        root = project_dir() / "data"
    else:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        root = Path(base) / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def app_version() -> str:
    """Version from version.txt next to the source tree or inside a frozen build."""
    candidates = [
        project_dir() / "version.txt",
        Path(__file__).resolve().parent.parent / "version.txt",
    ]
    for path in candidates:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return APP_VERSION_FALLBACK


def normalize_domain(value: str) -> str:
    """Turn ``chat.deepseek.com`` into ``https://chat.deepseek.com/``."""
    v = (value or "").strip()
    if not v:
        return DEFAULT_DOMAIN
    if "://" not in v:
        v = "https://" + v
    parts = urlsplit(v)
    if not parts.hostname:
        return DEFAULT_DOMAIN
    path = parts.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    return urlunsplit((parts.scheme or "https", parts.netloc, path, parts.query, ""))


@dataclass
class Settings:
    domain: str = DEFAULT_DOMAIN
    load_last_session: bool = True
    load_all_sessions: bool = False
    context_limit: int = 128000
    context_warn: float = 0.75
    sidebar_width: int = 276
    sidebar_visible: bool = True
    detect_limits: bool = True
    poll_seconds: int = 8
    user_agent: str = DEFAULT_USER_AGENT
    last_session_id: str | None = None
    window_geometry: str = ""
    zoom: dict[str, float] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "Settings":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {f.name for f in fields(cls)}
        data = {k: v for k, v in raw.items() if k in known}
        try:
            obj = cls(**data)
        except TypeError:
            return cls()
        obj.domain = normalize_domain(obj.domain)
        obj.context_limit = max(8000, int(obj.context_limit))
        obj.context_warn = min(0.99, max(0.3, float(obj.context_warn)))
        obj.sidebar_width = max(200, min(560, int(obj.sidebar_width)))
        obj.poll_seconds = max(3, int(obj.poll_seconds))
        if not isinstance(obj.zoom, dict):
            obj.zoom = {}
        return obj

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
