"""Real tokens through the real dependency: the auth path GVC shares with GAM."""

import time

from jose import jwt

from app.config import settings


def _token(sub="notes-user-1", secret=None, exp_in=3600):
    return jwt.encode(
        {"sub": sub, "username": "gecko", "exp": int(time.time()) + exp_in},
        secret or settings.jwt_secret_key,
        algorithm="HS256",
    )


def test_no_credentials_is_401_in_the_suite_error_shape(client):
    res = client.get("/api/projects")
    assert res.status_code == 401
    assert res.json()["detail"]["code"] == "unauthorized"


def test_a_token_notes_signed_is_accepted_and_records_a_shadow_user(client):
    headers = {"Authorization": f"Bearer {_token()}"}
    me = client.get("/api/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["data"]["id"] == "notes-user-1"
    assert me.json()["data"]["username"] == "gecko"
    assert client.get("/api/projects", headers=headers).status_code == 200


def test_a_token_signed_with_another_secret_is_refused(client):
    headers = {"Authorization": f"Bearer {_token(secret='some-other-secret-entirely')}"}
    assert client.get("/api/projects", headers=headers).status_code == 401


def test_an_expired_token_is_refused(client):
    headers = {"Authorization": f"Bearer {_token(exp_in=-10)}"}
    res = client.get("/api/projects", headers=headers)
    assert res.status_code == 401
    assert "expired" in res.json()["detail"]["message"]


def test_a_notes_push_can_be_a_users_first_request(client):
    """The project row needs the shadow user; a push must not depend on /api/me first."""
    headers = {"Authorization": f"Bearer {_token(sub='brand-new')}"}
    res = client.post("/api/projects/import", headers=headers,
                      json={"spec": {"spec_version": "0.1", "title": "Hi"}})
    assert res.status_code == 201, res.text


def test_the_dev_user_needs_development_mode_too(client, monkeypatch):
    monkeypatch.setattr(settings, "dev_auth_user", "dev")
    assert client.get("/api/projects").status_code == 401
    monkeypatch.setattr(settings, "environment", "development")
    assert client.get("/api/projects").status_code == 200
