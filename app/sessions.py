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
    # Peak volume of every conversation seen in this session. The site only
    # keeps one chat in the DOM at a time and re-renders it while streaming,
    # so a plain "current page size" made the counter jump back and forth.
    context_chats: dict[str, int] = field(default_factory=dict)
    # Per-chat map of virtual-list row key -> characters in that row. The site
    # keeps only a handful of messages in the DOM, so the sum of the visible
    # window stops growing once it slides; remembering every row makes the
    # counter grow with each new message.
    context_items: dict[str, dict[str, int]] = field(default_factory=dict)
    context_chat: str = ""

    def measure_context(
        self,
        chars: int,
        tokens: int = 0,
        chat_key: str = "",
        items: dict | None = None,
    ) -> bool:
        """Remember the biggest volume seen for every chat and sum them up.

        The counter must only grow while the user writes: switching chats or
        a partial DOM re-render may show fewer messages, but that is not a
        reason to roll the session counter back. A manual reset stores the
        current total in ``context_base_chars`` and keeps it as the baseline.

        ``items`` maps the virtual-list row key of every rendered message to
        its length. The chat is virtualised, so the sum of the visible window
        alone stops growing as soon as the window slides; remembering each row
        keeps the total honest.

        Returns True when the stored total changed.
        """
        chars = max(0, int(chars))
        key = str(chat_key or "").strip()
        previous = str(self.context_chat or "")

        # The page switched to the home screen while the old chat was still in
        # the DOM — ignore it, otherwise the previous chat gets counted twice.
        if not key and previous:
            return False

        before = int(self.context_chars or 0)

        chats = dict(self.context_chats or {})
        if not chats and int(self.context_chars or 0) > 0:
            # Migration from versions that tracked a single page volume. That
            # volume belonged to the chat that was on screen last, so seed the
            # current chat instead of creating a second, unrelated entry.
            chats[previous or key or "~"] = int(self.context_chars or 0)

        # Home screen -> real chat id: the just-created conversation used to be
        # measured under "", move its peak to the id instead of duplicating it.
        if not previous and key and "" in chats:
            pending = int(chats.pop("", 0))
            chats[key] = max(pending, int(chats.get(key, 0)))

        chats[key] = max(int(chats.get(key, 0)), chars)

        # Rows seen so far in this chat. A row only ever grows (streaming,
        # expanding a reasoning block), so keeping the maximum is enough.
        known = dict((self.context_items or {}).get(key) or {})
        fresh = items if isinstance(items, dict) else {}
        for item_key, size in fresh.items():
            item_key = str(item_key)
            try:
                size = max(0, int(size))
            except (TypeError, ValueError):
                continue
            if size > int(known.get(item_key, 0)):
                known[item_key] = size
        if known:
            self.context_items[key] = known
            chats[key] = max(chats[key], sum(int(v) for v in known.values()))

        # Keep the map bounded without losing counted characters: move the
        # smallest chats into an archive bucket so the total never drops.
        while len(chats) > 80:
            candidates = [k for k in chats if k != "~"]
            if not candidates:
                break
            smallest = min(candidates, key=lambda k: chats[k])
            moved = int(chats.pop(smallest, 0))
            chats["~"] = int(chats.get("~", 0)) + moved

        self.context_chats = chats
        self.context_chars = sum(int(v) for v in chats.values())
        self.context_tokens = max(0, int(round(self.context_chars / 2.5)))
        self.context_chat = key
        self.context_at = time.time()
        return self.context_chars != before or key != previous

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


def format_count(value: int) -> str:
    """Thousands separated by spaces: 12 945."""
    return f"{max(0, int(value or 0)):,}".replace(",", " ")


def human_tokens(tokens: int) -> str:
    return format_count(tokens)
