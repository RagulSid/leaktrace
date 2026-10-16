"""The customer is bound to the login token on the server: a token for tenant A never reaches B."""

import json

import pytest
from fastapi.testclient import TestClient

from app.api import auth
from app.api.main import app
from app.cli import bootstrap
from app.graph.client import TenantGraph
from tests.conftest import DATACENTER_PACK, fresh_tenant

PASSWORD = "practice-only-password"


@pytest.fixture
def two_tenants():
    c = TestClient(app)
    made = []
    for _ in range(2):
        t = fresh_tenant()
        bootstrap(t, password=PASSWORD)
        made.append(t)
        tok = login(c, t, "manager1")
        r = c.post("/assets/import", json=json.loads(DATACENTER_PACK.read_text(encoding="utf-8")), headers=h(tok))
        assert r.status_code == 200, r.text
    yield c, made
    for t in made:
        TenantGraph(t).delete()


def login(c, tenant, user, password=PASSWORD):
    r = c.post("/auth/login", json={"tenant": tenant, "username": user, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def h(token):
    return {"Authorization": f"Bearer {token}"}


def test_token_for_a_cannot_see_b(two_tenants):
    c, (a, b) = two_tenants
    rep = c.post("/reports", json={"text": "water under Rack A1"}, headers=h(login(c, a, "staff1"))).json()
    op_a, op_b = login(c, a, "operator1"), login(c, b, "operator1")

    assert [i["id"] for i in c.get("/incidents", headers=h(op_a)).json()] == [rep["incident"]]
    assert c.get("/incidents", headers=h(op_b)).json() == []
    assert c.get(f"/incidents/{rep['incident']}", headers=h(op_b)).status_code == 404
    assert c.post(f"/incidents/{rep['incident']}/investigate", headers=h(op_b)).status_code == 404
    # a tenant in the query string or body is ignored: the token decides
    assert c.get(f"/incidents?tenant={a}", headers=h(op_b)).json() == []
    assert c.get(f"/reports/{rep['code']}", headers=h(login(c, b, "staff1"))).status_code == 404


def test_tampered_expired_and_missing_tokens_are_rejected(two_tenants):
    c, (a, b) = two_tenants
    tok = login(c, b, "operator1")
    claims, sig = tok.split(".")
    forged_claims = auth._b64(json.dumps({**json.loads(auth._unb64(claims)), "tenant": a}, sort_keys=True).encode())
    assert c.get("/incidents", headers=h(f"{forged_claims}.{sig}")).status_code == 401
    expired, _ = auth.issue_token("operator1", "operator", a, ttl_s=-1)
    assert c.get("/incidents", headers=h(expired)).status_code == 401
    assert c.get("/incidents").status_code == 401
    assert c.get("/incidents", headers=h("not-a-token")).status_code == 401


def test_login_failures_look_the_same(two_tenants):
    c, (a, _) = two_tenants
    for body in [{"tenant": a, "username": "operator1", "password": "wrong"},
                 {"tenant": a, "username": "nobody", "password": PASSWORD},
                 {"tenant": "t_does_not_exist", "username": "operator1", "password": PASSWORD},
                 {"tenant": "Bad Tenant!", "username": "operator1", "password": PASSWORD}]:
        r = c.post("/auth/login", json=body)
        assert r.status_code == 401 and r.json()["detail"] == "wrong tenant, username or password"


def test_roles_are_enforced(two_tenants):
    c, (a, _) = two_tenants
    meters, staff = login(c, a, "meters1"), login(c, a, "staff1")
    ok = c.post("/readings", json={"readings": [{"id": "FM-01", "ts": 1.0, "value": 70.0}]}, headers=h(meters))
    assert ok.status_code == 200
    assert c.get("/incidents", headers=h(meters)).status_code == 403
    assert c.post("/reports", json={"text": "water"}, headers=h(meters)).status_code == 403
    assert c.post("/assets/import", json={"nodes": []}, headers=h(staff)).status_code == 403
    inc = c.post("/reports", json={"text": "water in Row A"}, headers=h(staff)).json()["incident"]
    assert c.post(f"/incidents/{inc}/investigate", headers=h(staff)).status_code == 403


def test_passwords_are_stored_hashed(two_tenants):
    _, (a, _) = two_tenants
    u = TenantGraph(a)._g.ro_query("MATCH (u:User {id:'operator1'}) RETURN properties(u)").result_set[0][0]
    assert PASSWORD not in json.dumps(u) and len(u["pw_hash"]) == 64 and u["source"] == "synthetic"
