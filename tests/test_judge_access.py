"""Judge access: one shared practice password for the operator, field crew, staff and safety accounts (shown on the
sign-in screen), a separate private password for the manager and meters accounts (never sent), and a manager-only
"Reset practice data" that rebuilds the demo customer with ensure-demo."""

import time

import pytest
from fastapi.testclient import TestClient

from app import cli, config
from app.api.auth import login
from app.api.main import app
from app.graph.client import TenantGraph, get_db, rows
from scenario_generator.run import Session
from tests.conftest import fresh_tenant

SHARED, MANAGER = "shared-practice-password", "private-manager-password"


@pytest.fixture
def demo(monkeypatch):
    t = fresh_tenant()
    cli.bootstrap(t, password=SHARED, manager_password=MANAGER)
    monkeypatch.setattr(config, "DEMO_TENANT", t)
    monkeypatch.setattr(config, "DEMO_PASSWORD", SHARED)
    monkeypatch.setattr(config, "MANAGER_PASSWORD", MANAGER)
    monkeypatch.setattr(config, "DEMO_SEED_COMMAND", "")  # map only: fast; the story is tested in test_deploy_startup
    yield t, TestClient(app)
    if TenantGraph(t).name in get_db().list_graphs():
        TenantGraph(t).delete()


def test_shared_password_for_public_roles_private_one_for_the_manager(demo):
    t, _ = demo
    for user in ("operator1", "operator2", "tech1", "tech2", "staff1", "safety1"):
        assert login(t, user, SHARED) is not None, user
        assert login(t, user, MANAGER) is None, user
    for user in ("manager1", "meters1"):
        assert login(t, user, MANAGER) is not None and login(t, user, SHARED) is None, user


def test_sign_in_screen_shows_the_shared_password_never_the_managers(demo, monkeypatch):
    _, c = demo
    info = c.get("/public/info").json()
    assert info["practice_sign_in"] == {"accounts": ["operator1", "tech1", "staff1", "safety1"], "password": SHARED}
    for path in ("/public/info", "/health", "/how-it-works/summary"):
        assert MANAGER not in c.get(path).text
    monkeypatch.setattr(config, "SHOW_PRACTICE_PASSWORD", False)
    assert c.get("/public/info").json()["practice_sign_in"] is None


def test_only_the_manager_resets_and_the_practice_data_comes_back(demo):
    t, c = demo
    sess = Session(t, SHARED, manager_password=MANAGER)
    sess.post("/reports", "staff1", {"text": "Water under Rack B1 in Row B, small puddle."})
    before = rows(TenantGraph(t).read("stats"))[0]["nodeCount"]
    assert sess.post("/practice/reset", "operator1", expect=403)
    assert sess.post("/practice/reset", "manager1", expect=202) == {"status": "resetting"}
    deadline = time.time() + 60
    while time.time() < deadline:
        h = c.get("/health")
        if h.status_code == 200 and rows(TenantGraph(t).read("stats"))[0]["nodeCount"] < before:
            break
        time.sleep(0.3)
    assert c.get("/health").json() == {"falkordb_reachable": True, "demo_seeded": True}
    assert TenantGraph(t)._g.ro_query("MATCH (r:Report) RETURN count(r)").result_set == [[0]]  # the report is gone
    assert login(t, "operator1", SHARED) and login(t, "manager1", MANAGER)  # same passwords afterwards


def test_reset_is_only_for_the_demo_customer(demo, monkeypatch):
    other = fresh_tenant()
    try:
        cli.bootstrap(other, password=SHARED, manager_password=MANAGER)
        assert Session(other, SHARED, manager_password=MANAGER).post("/practice/reset", "manager1", expect=403)
    finally:
        TenantGraph(other).delete()
