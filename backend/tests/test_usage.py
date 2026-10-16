"""Spend: priced per call, attributed to projects and turns, read back as totals."""

from app.models.usage import UsageEvent
from app.providers.base import Reply, Usage
from app.usage import events as usage_events
from app.usage import pricing


def test_current_claude_models_are_priced_from_the_most_specific_entry():
    assert pricing.cost_for("anthropic", "claude-opus-5-5", 1_000_000, 1_000_000) == (24.0, "USD")
    assert pricing.cost_for("anthropic", "claude-opus-5", 1_000_000, 0) == (5.0, "USD")
    assert pricing.cost_for("anthropic", "claude-sonnet-5-5", 0, 1_000_000) == (10.0, "USD")
    assert pricing.cost_for("anthropic", "claude-haiku-5-5", 1_000_000, 0) == (0.1, "USD")
    assert pricing.cost_for("anthropic", "claude-fable-5-1", 1_000_000, 0) == (10.0, "USD")
    assert pricing.cost_for("ollama", "qwen3", 10**6, 10**6) == (0.0, "USD")
    assert pricing.cost_for("custom", "anything", 10**6, 10**6) is None


def reply(provider="anthropic", model="claude-opus-5-5", tokens_in=1000, tokens_out=500):
    return Reply(text="", usage=Usage(tokens_in, tokens_out), model=model, provider_type=provider)


def test_a_reply_is_recorded_against_its_project_and_turn(session):
    cost = usage_events.record_reply(session, user_id="u", project_id="p", turn_id="t",
                                     reply=reply())
    assert cost == round(1000 / 1e6 * 4 + 500 / 1e6 * 20, 6)
    [row] = session.query(UsageEvent).all()
    assert (row.project_id, row.turn_id, row.units, row.cost_estimated) == ("p", "t", 1500, True)


def test_an_unmeasured_call_records_nothing_and_an_unpriced_one_no_cost(session):
    assert usage_events.record_reply(session, user_id="u", project_id=None, turn_id=None,
                                     reply=reply(tokens_in=0, tokens_out=0)) is None
    assert session.query(UsageEvent).count() == 0
    assert usage_events.record_reply(session, user_id="u", project_id=None, turn_id=None,
                                     reply=reply(provider="custom")) is None
    assert session.query(UsageEvent).one().cost is None


def test_totals_overall_per_project_and_by_model_over_http(auth_client, session):
    project = auth_client.post("/api/projects", json={"spec": {"title": "T", "segments": []}}).json()["data"]
    from tests.conftest import TEST_USER_ID
    usage_events.record_reply(session, user_id=TEST_USER_ID, project_id=project["id"],
                              turn_id="t1", reply=reply())
    usage_events.record_reply(session, user_id=TEST_USER_ID, project_id=None, turn_id="t2",
                              reply=reply(provider="custom", model="x"))

    overall = auth_client.get("/api/usage").json()["data"]
    assert overall["totals"]["total_events"] == 2
    # One call could not be priced, so the total says it is a floor.
    assert overall["totals"]["priced_events"] == 1
    assert overall["totals"]["estimated"] is True
    assert {(r["provider"], r["model"]) for r in overall["by_provider"]} == {
        ("anthropic", "claude-opus-5-5"), ("custom", "x")}

    mine = auth_client.get(f"/api/usage/projects/{project['id']}").json()["data"]
    assert mine["total_events"] == 1 and mine["tokens"] == 1500
    assert auth_client.get("/api/usage/projects/nope").status_code == 404
