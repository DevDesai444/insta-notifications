"""Configuration, loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional convenience, not required in containers
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is a soft dependency
    def load_dotenv(*_args, **_kwargs):
        return False


DEFAULT_KEYWORDS = (
    "new grad,newgrad,new-grad,grad role,entry level,entry-level,university grad,"
    "campus,intern,internship,2026,2027,swe,sde,software engineer,hiring,apply,"
    "applications open,now open,workday,greenhouse,lever,referral,job,role,opening"
)


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class Config:
    # --- who to watch -------------------------------------------------
    target_username: str = "zero2sudo"

    # --- Instagram credentials (use a burner account that follows target)
    ig_username: str = ""
    ig_password: str = ""
    ig_verification_code: str = ""  # TOTP seed for 2FA, optional
    # Preferred over username/password: paste the `sessionid` cookie from a
    # browser you're already logged into. No password ever touches disk, and
    # no throwaway account needs creating.
    ig_sessionid: str = ""

    # --- polling ------------------------------------------------------
    poll_interval: int = 60
    poll_jitter: float = 0.2
    posts_per_poll: int = 5
    check_stories: bool = True
    check_posts: bool = True

    # --- notification backend ----------------------------------------
    backend: str = "ntfy"
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str = ""
    ntfy_token: str = ""
    ntfy_priority: int = 5  # 5 = max: bypasses iOS notification grouping delays
    pushover_token: str = ""
    pushover_user: str = ""
    attach_images: bool = True

    # --- link extraction ---------------------------------------------
    vision_enabled: bool = True
    vision_model: str = "claude-opus-5"
    anthropic_api_key: str = ""
    vision_max_per_poll: int = 12   # cost guard against a 30-frame story dump

    # --- filtering ----------------------------------------------------
    notify_all: bool = True
    keywords: tuple[str, ...] = ()

    # --- storage ------------------------------------------------------
    data_dir: Path = field(default_factory=lambda: Path("data"))

    # Ignore anything older than this, so a wiped state file does not
    # replay last week's posts as "new".
    max_item_age_hours: int = 48

    # --- behaviour on first run ---------------------------------------
    # True  -> record everything currently visible without notifying (no spam burst)
    # False -> notify about everything found on the very first poll
    seed_on_first_run: bool = True

    @property
    def session_file(self) -> Path:
        return self.data_dir / "ig_session.json"

    @property
    def state_db(self) -> Path:
        return self.data_dir / "state.db"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def has_instagram_auth(self) -> bool:
        return bool(self.ig_sessionid or (self.ig_username and self.ig_password))

    @property
    def use_vision(self) -> bool:
        return self.vision_enabled and bool(self.anthropic_api_key)

    @classmethod
    def from_env(cls, env_file: str | os.PathLike | None = ".env") -> "Config":
        if env_file and Path(env_file).exists():
            load_dotenv(env_file)
        else:
            load_dotenv()

        raw_keywords = os.getenv("KEYWORDS", DEFAULT_KEYWORDS)
        keywords = tuple(
            k.strip().lower() for k in raw_keywords.split(",") if k.strip()
        )

        return cls(
            target_username=os.getenv("IG_TARGET_USERNAME", "zero2sudo").lstrip("@"),
            ig_username=os.getenv("IG_USERNAME", ""),
            ig_password=os.getenv("IG_PASSWORD", ""),
            ig_verification_code=os.getenv("IG_TOTP_SEED", ""),
            ig_sessionid=os.getenv("IG_SESSIONID", "").strip().strip('"').strip("'"),
            poll_interval=_int("POLL_INTERVAL_SECONDS", 60),
            poll_jitter=_float("POLL_JITTER", 0.2),
            posts_per_poll=_int("POSTS_PER_POLL", 5),
            check_stories=_bool("CHECK_STORIES", True),
            check_posts=_bool("CHECK_POSTS", True),
            backend=os.getenv("NOTIFY_BACKEND", "ntfy").strip().lower(),
            ntfy_server=os.getenv("NTFY_SERVER", "https://ntfy.sh").rstrip("/"),
            ntfy_topic=os.getenv("NTFY_TOPIC", "").strip(),
            ntfy_token=os.getenv("NTFY_TOKEN", "").strip(),
            ntfy_priority=_int("NTFY_PRIORITY", 5),
            pushover_token=os.getenv("PUSHOVER_TOKEN", "").strip(),
            pushover_user=os.getenv("PUSHOVER_USER", "").strip(),
            attach_images=_bool("ATTACH_IMAGES", True),
            vision_enabled=_bool("VISION_ENABLED", True),
            vision_model=os.getenv("VISION_MODEL", "claude-opus-5"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
            vision_max_per_poll=_int("VISION_MAX_PER_POLL", 12),
            notify_all=_bool("NOTIFY_ALL", True),
            keywords=keywords,
            max_item_age_hours=_int("MAX_ITEM_AGE_HOURS", 48),
            data_dir=Path(os.getenv("DATA_DIR", "data")),
            seed_on_first_run=_bool("SEED_ON_FIRST_RUN", True),
        )

    def validate(self) -> list[str]:
        """Return a list of human-readable configuration problems."""
        problems: list[str] = []
        if not self.target_username:
            problems.append("IG_TARGET_USERNAME is empty.")
        if self.check_stories and not self.has_instagram_auth:
            problems.append(
                "Instagram sign-in is required to read stories. Set either "
                "IG_SESSIONID (paste the `sessionid` cookie from a browser "
                "you're logged into — easiest, no password stored) or "
                "IG_USERNAME + IG_PASSWORD. Whichever account you use must "
                f"follow @{self.target_username}."
            )
        if self.backend == "ntfy" and not self.ntfy_topic:
            problems.append("NTFY_TOPIC is required when NOTIFY_BACKEND=ntfy.")
        if self.backend == "pushover" and not (
            self.pushover_token and self.pushover_user
        ):
            problems.append(
                "PUSHOVER_TOKEN and PUSHOVER_USER are required when "
                "NOTIFY_BACKEND=pushover."
            )
        if self.backend not in {"ntfy", "pushover", "console"}:
            problems.append(
                f"Unknown NOTIFY_BACKEND '{self.backend}' "
                "(expected ntfy, pushover, or console)."
            )
        if self.poll_interval < 20:
            problems.append(
                "POLL_INTERVAL_SECONDS below 20 will get the Instagram account "
                "rate-limited or blocked. Use 30 or more."
            )
        return problems
