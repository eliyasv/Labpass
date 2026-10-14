import pytest

from labpass.config import Settings

DATABASE = "postgresql+psycopg://localhost/labpass"


def test_configuration_fails_safely(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL is required"):
        Settings.from_env()
    monkeypatch.setenv("DATABASE_URL", "sqlite:///test.db")
    with pytest.raises(RuntimeError, match="postgresql"):
        Settings.from_env()
    monkeypatch.setenv("DATABASE_URL", DATABASE)
    monkeypatch.delenv("APP_ORIGIN", raising=False)
    with pytest.raises(RuntimeError, match="APP_ORIGIN is required"):
        Settings.from_env()
    monkeypatch.setenv("APP_ORIGIN", "https://labpass.example.com")
    monkeypatch.delenv("LABPASS_COOKIE_SECURE", raising=False)
    settings = Settings.from_env()
    assert settings.cookie_secure and settings.cookie_name.startswith("__Host-")
    monkeypatch.setenv("LABPASS_COOKIE_SECURE", "false")
    with pytest.raises(RuntimeError, match="loopback"):
        Settings.from_env()
    monkeypatch.setenv("APP_ORIGIN", "http://127.0.0.1:8000")
    assert not Settings.from_env().cookie_secure
    monkeypatch.setenv("LABPASS_COOKIE_SECURE", "unexpected")
    with pytest.raises(RuntimeError, match="true or false"):
        Settings.from_env()


@pytest.mark.parametrize(
    "origin",
    [
        "",
        "ftp://localhost",
        "https://user:pass@example.com",
        "https://example.com/path",
        "https://example.com?x=1",
    ],
)
def test_invalid_origin(origin):
    with pytest.raises(RuntimeError, match="APP_ORIGIN"):
        Settings(DATABASE, origin)


def test_secure_cookie_requires_https():
    with pytest.raises(RuntimeError, match="HTTPS"):
        Settings(DATABASE, "http://localhost:8000")


@pytest.mark.parametrize(
    "origin",
    [
        "https://localhost:no-port",
        "https://localhost:0",
        "https://localhost:65536",
        "https://[invalid",
    ],
)
def test_invalid_origin_port_or_host(origin):
    with pytest.raises(RuntimeError, match="APP_ORIGIN"):
        Settings(DATABASE, origin)
