from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

STATE_OK = "ok"
STATE_WARN = "warn"
STATE_LIMITED = "limited"
STATE_BLOCKED = "blocked"
STATE_EXHAUSTED = "exhausted"

STATE_TITLES = {
    STATE_OK: "в норме",
    STATE_WARN: "контекст почти заполнен",
    STATE_LIMITED: "временное ограничение",
    STATE_BLOCKED: "недоступна",
    STATE_EXHAUSTED: "перенесена",
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def new_id() -> str:
    return uuid.uuid4().hex[:10]


@dataclass
class Session:
    id: str
    name: str
    created_at: str = field(default_factory=now_iso)
    last_used: str | None = None
    last_url: str | None = None
    status: str = STATE_OK
    status_reason: str = ""
    status_at: float = 0.0
    status_reset_at: float = 0.0
    limit_reset_at: float = 0.0
    limit_reset_text: str = ""
    usage_date: str = field(default_factory=today_str)
    usage_count: int = 0
    context_chars: int = 0
    context_tokens: int = 0
    context_base_chars: int = 0
    context_reset_at: float = 0.0
    context_at: float = 0.0

    def measure_context(self, chars: int, tokens: int) -> None:
        chars = max(0, int(chars))
        self.context_chars = chars
        self.context_tokens = max(0, int(tokens))
        self.context_at = time.time()
        if chars < int(self.context_base_chars or 0):
            # The chat was cleared or switched — start counting the new one
            # from zero instead of waiting until it outgrows the old baseline.
            self.context_base_chars = chars

    @property
    def used_context_chars(self) -> int:
        """Characters added since the last token-counter reset."""
        return max(0, int(self.context_chars or 0) - int(self.context_base_chars or 0))

    @property
    def used_context_tokens(self) -> int:
        """Estimated tokens added since the last token-counter reset."""
        chars = self.used_context_chars
        if chars <= 0:
            return 0
        return max(1, int(round(chars / 2.5)))

    def reset_context(self) -> None:
        """Zero the token counter, keeping the already measured volume as a base."""
        self.context_base_chars = max(0, int(self.context_chars or 0))
        self.context_reset_at = time.time()

    def roll_day(self) -> bool:
        """Reset the daily counter when the date changes. True if it was reset."""
        today = today_str()
        if self.usage_date != today:
            self.usage_date = today
            self.usage_count = 0
            return True
        return False

    def add_usage(self, amount: int = 1) -> None:
        if amount <= 0:
            return
        self.roll_day()
        self.usage_count += amount
        self.last_used = now_iso()

    def reset_usage(self) -> None:
        self.usage_date = today_str()
        self.usage_count = 0
        self.limit_reset_at = 0.0
        self.limit_reset_text = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


class SessionStore:
    def __init__(self, path: Path):
        self.path = path
        self.sessions: list[Session] = []

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        items = raw.get("sessions") if isinstance(raw, dict) else None
        out: list[Session] = []
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    try:
                        out.append(Session.from_dict(item))
                    except TypeError:
                        continue
        self.sessions = out

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "sessions": [s.to_dict() for s in self.sessions]}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self, sid: str) -> Session | None:
        for s in self.sessions:
            if s.id == sid:
                return s
        return None

    def index_of(self, sid: str) -> int:
        for i, s in enumerate(self.sessions):
            if s.id == sid:
                return i
        return -1

    def create(self, name: str | None = None) -> Session:
        if not name:
            taken = {s.name for s in self.sessions}
            n = 1
            while f"Сессия {n}" in taken:
                n += 1
            name = f"Сессия {n}"
        s = Session(id=new_id(), name=name, last_used=now_iso())
        self.sessions.append(s)
        return s

    def remove(self, sid: str) -> bool:
        idx = self.index_of(sid)
        if idx < 0:
            return False
        del self.sessions[idx]
        return True

    def touch(self, sid: str) -> None:
        s = self.get(sid)
        if s is not None:
            s.last_used = now_iso()

    def __len__(self) -> int:
        return len(self.sessions)


def human_age(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return "—"
    delta = time.time() - dt.timestamp()
    if delta < 60:
        return "только что"
    if delta < 3600:
        return f"{int(delta // 60)} мин назад"
    if delta < 86400:
        return f"{int(delta // 3600)} ч назад"
    return dt.strftime("%d.%m %H:%M")


def human_tokens(tokens: int) -> str:
    tokens = max(0, int(tokens or 0))
    if tokens >= 10000:
        return f"{tokens / 1000:.0f}K"
    if tokens >= 1000:
        return f"{tokens / 1000:.1f}K"
    return str(tokens)
