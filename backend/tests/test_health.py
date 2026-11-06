def test_health_is_public(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_config_is_public_and_carries_only_the_sign_in_address(client):
    res = client.get("/api/config")
    assert res.status_code == 200
    # Readable by anyone, so adding a field has to be a deliberate act.
    assert set(res.json()["data"]) == {"sign_in_url", "ai_backend", "suite_base_url"}


def test_people_sign_in_at_the_suites_public_address_and_notes_are_separate(monkeypatch):
    from app.config import Settings

    for name in ("SUITE_BASE_URL", "SUITE_PUBLIC_URL", "NOTES_URL", "NOTES_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 64)
    defaults = Settings(_env_file=None)
    assert defaults.sign_in_url == "https://suite.geckopico.com"
    assert defaults.notes_url == "https://notes.geckopico.com"

    # An internal SUITE_BASE_URL (a compose service) is no use to a browser.
    monkeypatch.setenv("SUITE_BASE_URL", "http://suite-backend:8000")
    monkeypatch.setenv("SUITE_PUBLIC_URL", "https://suite.example/")
    assert Settings(_env_file=None).sign_in_url == "https://suite.example"

    # The old name is read by neither: set to the suite, it sent every call to Notes there.
    monkeypatch.setenv("NOTES_BASE_URL", "https://suite.example")
    old = Settings(_env_file=None)
    assert old.notes_url == "https://notes.geckopico.com"
