"""Environment-driven configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from mt4_executor.errors import ConfigError

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is a declared dependency
    def load_dotenv(*_args, **_kwargs):
        return False


@dataclass(frozen=True)
class Settings:
    """Connection settings for a single MetaApi-managed MT4 account."""

    token: str
    login: str
    password: str
    server: str
    account_name: str = "mt4-executor"
    magic: int = 1000
    platform: str = "mt4"
    region: Optional[str] = None

    @classmethod
    def from_env(cls, *, load_env_file: bool = True) -> "Settings":
        """Build settings from environment variables (and an optional .env file)."""
        if load_env_file:
            load_dotenv()

        # One-flag demo/live switch: when MT_MODE is set, the broker credentials
        # are read from MODE-prefixed vars (e.g. DEMO_MT_LOGIN / LIVE_MT_SERVER),
        # falling back to the bare vars. Unset MT_MODE = bare vars only (default).
        mode = (os.getenv("MT_MODE") or "").strip().lower()

        def _pick(base: str) -> Optional[str]:
            if mode:
                scoped = os.getenv(f"{mode.upper()}_{base}")
                if scoped:
                    return scoped
            return os.getenv(base)

        sources = {
            "token": ("METAAPI_TOKEN", os.getenv("METAAPI_TOKEN")),
            "login": ("MT_LOGIN", _pick("MT_LOGIN")),
            "password": ("MT_PASSWORD", _pick("MT_PASSWORD")),
            "server": ("MT_SERVER", _pick("MT_SERVER")),
        }
        missing = [env for _, (env, val) in sources.items() if not val]
        if missing:
            raise ConfigError(
                "Missing required environment variables: "
                + ", ".join(sorted(missing))
                + ". Copy .env.example to .env and fill it in."
            )
        values = {field: val for field, (_env, val) in sources.items()}

        magic_raw = os.getenv("MT_MAGIC", "1000")
        try:
            magic = int(magic_raw)
        except ValueError as exc:
            raise ConfigError(f"MT_MAGIC must be an integer, got {magic_raw!r}") from exc

        return cls(
            token=values["token"],
            login=values["login"],
            password=values["password"],
            server=values["server"],
            account_name=os.getenv("MT_ACCOUNT_NAME", "mt4-executor"),
            magic=magic,
            region=os.getenv("METAAPI_REGION") or None,
        )
