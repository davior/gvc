"""GAM as the library: search, lookup, and how GAM failing is reported."""

import time

from jose import jwt

from app.config import settings
from tests.fake_siblings import GAM, gam_asset, hit


def _token(sub="notes-user-1"):
    return jwt.encode({"sub": sub, "username": "gecko", "exp": int(time.time()) + 3600},
                      settings.jwt_secret_key, algorithm="HS256")


def test_a_hit_carries_the_moment_and_absolute_signed_urls(auth_client, siblings):
    reel = gam_asset("g1", "Archive interview, 1971")
    siblings.hits = [hit(reel, start=734.0, end=741.5, snippet="the «salt» road")]

    body = auth_client.get("/api/gam/search", params={"q": "salt road"}).json()

    assert body["total"] == 1
    top = body["data"][0]
    assert (top["start_time"], top["end_time"]) == (734.0, 741.5)
    assert top["snippet"] == "the «salt» road"
    assert top["asset"]["file_url"] == f"{GAM}/media/g1.bin?exp=1&sig=x"
    assert top["asset"]["thumb_url"] == f"{GAM}/media/g1.jpg?exp=1&sig=x"


def test_a_gam_without_end_times_still_answers(auth_client, siblings):
    """Before gam#36, hits had no end_time. The editor sizes the moment itself then."""
    siblings.hits = [hit(gam_asset("g1", "Reel"), start=10.0)]
    top = auth_client.get("/api/gam/search", params={"q": "x"}).json()["data"][0]
    assert top["start_time"] == 10.0 and top["end_time"] is None


def test_documents_are_not_offered_for_a_video(auth_client, siblings):
    siblings.hits = [hit(gam_asset("d1", "Report", "document")), hit(gam_asset("i1", "Map", "image"))]
    body = auth_client.get("/api/gam/search", params={"q": "x"}).json()
    assert [h["asset"]["id"] for h in body["data"]] == ["i1"]


def test_the_type_filter_is_passed_to_gam(auth_client, siblings):
    auth_client.get("/api/gam/search", params={"q": "x", "type": "video"})
    assert siblings.gam_requests()[0].url.params["asset_type"] == "video"
    assert auth_client.get("/api/gam/search", params={"q": "x", "type": "document"}).status_code == 422


def test_an_empty_query_does_not_reach_gam(auth_client, siblings):
    assert auth_client.get("/api/gam/search", params={"q": "  "}).json()["total"] == 0
    assert siblings.gam_requests() == []


def test_the_callers_own_token_is_what_gam_sees(client, siblings):
    token = _token()
    res = client.get("/api/gam/search", params={"q": "x"},
                     headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert siblings.gam_requests()[0].headers["authorization"] == f"Bearer {token}"


def test_nothing_is_forwarded_for_a_caller_this_app_did_not_verify(client, siblings):
    res = client.get("/api/gam/search", params={"q": "x"},
                     headers={"Authorization": "Bearer not-a-real-token"})
    assert res.status_code == 401
    assert siblings.gam_requests() == []


def test_gam_down_is_a_502_that_names_the_library(auth_client, siblings):
    siblings.gam_down = True
    res = auth_client.get("/api/gam/search", params={"q": "x"})
    assert res.status_code == 502
    assert res.json()["detail"]["code"] == "gam_unavailable"


def test_gam_refusing_the_session_names_the_secret_mismatch(auth_client, siblings):
    siblings.gam_status = 401
    res = auth_client.get("/api/gam/search", params={"q": "x"})
    assert res.status_code == 502
    assert res.json()["detail"]["code"] == "gam_rejected_session"
    assert "JWT_SECRET_KEY" in res.json()["detail"]["message"]


def test_lookup_returns_fresh_urls_and_null_for_what_is_gone(auth_client, siblings):
    siblings.assets = {"g1": gam_asset("g1", "Reel")}
    res = auth_client.post("/api/gam/assets/lookup", json={"ids": ["g1", "gone", "g1"]})
    assets = res.json()["data"]["assets"]
    assert assets["g1"]["name"] == "Reel"
    assert assets["g1"]["file_url"].startswith(GAM)
    assert assets["gone"] is None
    # Asked once each, however often a spec mentions it.
    assert len(siblings.gam_requests()) == 2
