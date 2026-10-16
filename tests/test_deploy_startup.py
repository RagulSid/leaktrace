"""The startup step for a fresh container: the demo customer is created and seeded only when its graph is
empty, and never with a made-up password."""

import pytest

from app import cli
from app.graph.client import TenantGraph, get_db
from tests.conftest import DATACENTER_PACK, fresh_tenant


@pytest.fixture
def tenant():
    t = fresh_tenant()
    yield t
    if TenantGraph(t).name in get_db().list_graphs():
        TenantGraph(t).delete()


def test_seeds_an_empty_graph_once(tenant):
    first = cli.ensure_demo(tenant, str(DATACENTER_PACK), password="practice-only-password")
    assert first["seeded"] is True and first["nodes"] == 49 and "operator1" in first["users"]
    again = cli.ensure_demo(tenant, str(DATACENTER_PACK), password="practice-only-password")
    assert again["seeded"] is False and again["nodes"] > 0
    from app.api.auth import login

    assert login(tenant, "operator1", "practice-only-password")["role"] == "operator"


def test_refuses_without_a_demo_password(tenant, monkeypatch):
    monkeypatch.delenv("LEAKTRACE_DEMO_PASSWORD", raising=False)
    with pytest.raises(cli.Refused):
        cli.ensure_demo(tenant, str(DATACENTER_PACK))
    assert TenantGraph(tenant).name not in get_db().list_graphs()  # nothing half-created
