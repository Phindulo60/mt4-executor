import pytest

from mt4_executor.config import Settings
from mt4_executor.errors import ConfigError

ENV_KEYS = ["METAAPI_TOKEN", "MT_LOGIN", "MT_PASSWORD", "MT_SERVER",
            "MT_ACCOUNT_NAME", "MT_MAGIC", "METAAPI_REGION", "MT_MODE",
            "DEMO_MT_LOGIN", "DEMO_MT_PASSWORD", "DEMO_MT_SERVER",
            "LIVE_MT_LOGIN", "LIVE_MT_PASSWORD", "LIVE_MT_SERVER"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _set_required(monkeypatch):
    monkeypatch.setenv("METAAPI_TOKEN", "tok")
    monkeypatch.setenv("MT_LOGIN", "12345")
    monkeypatch.setenv("MT_PASSWORD", "secret")
    monkeypatch.setenv("MT_SERVER", "Broker-Demo")


def test_from_env_happy_path(monkeypatch):
    _set_required(monkeypatch)
    s = Settings.from_env(load_env_file=False)
    assert s.token == "tok"
    assert s.login == "12345"
    assert s.server == "Broker-Demo"
    assert s.magic == 1000
    assert s.account_name == "mt4-executor"
    assert s.region is None


def test_missing_required_raises(monkeypatch):
    monkeypatch.setenv("METAAPI_TOKEN", "tok")
    with pytest.raises(ConfigError) as exc:
        Settings.from_env(load_env_file=False)
    assert "MT_LOGIN" in str(exc.value)


def test_optional_overrides(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("MT_ACCOUNT_NAME", "prod-mt4")
    monkeypatch.setenv("MT_MAGIC", "777")
    monkeypatch.setenv("METAAPI_REGION", "london")
    s = Settings.from_env(load_env_file=False)
    assert s.account_name == "prod-mt4"
    assert s.magic == 777
    assert s.region == "london"


def test_invalid_magic_raises(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("MT_MAGIC", "not-a-number")
    with pytest.raises(ConfigError):
        Settings.from_env(load_env_file=False)


def test_mode_selects_prefixed_vars(monkeypatch):
    monkeypatch.setenv("METAAPI_TOKEN", "tok")
    monkeypatch.setenv("MT_MODE", "live")
    monkeypatch.setenv("DEMO_MT_LOGIN", "111")
    monkeypatch.setenv("DEMO_MT_PASSWORD", "demopw")
    monkeypatch.setenv("DEMO_MT_SERVER", "Broker-Demo")
    monkeypatch.setenv("LIVE_MT_LOGIN", "999")
    monkeypatch.setenv("LIVE_MT_PASSWORD", "livepw")
    monkeypatch.setenv("LIVE_MT_SERVER", "Broker-Live")
    s = Settings.from_env(load_env_file=False)
    assert s.login == "999"
    assert s.password == "livepw"
    assert s.server == "Broker-Live"


def test_mode_falls_back_to_bare_vars(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("MT_MODE", "demo")
    s = Settings.from_env(load_env_file=False)
    assert s.login == "12345"
    assert s.server == "Broker-Demo"


def test_unset_mode_uses_bare_vars(monkeypatch):
    _set_required(monkeypatch)
    monkeypatch.setenv("DEMO_MT_LOGIN", "should-be-ignored")
    s = Settings.from_env(load_env_file=False)
    assert s.login == "12345"
