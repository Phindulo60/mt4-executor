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

        required = {
            "METAAPI_TOKEN": "token",
            "MT_LOGIN": "login",
            "MT_PASSWORD": "password",
            "MT_SERVER": "server",
        }
        values = {field: os.getenv(env) for env, field in required.items()}
        missing = [env for env, field in required.items() if not values[field]]
        if missing:
            raise ConfigError(
                "Missing required environment variables: "
                + ", ".join(sorted(missing))
                + ". Copy .env.example to .env and fill it in."
            )

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
