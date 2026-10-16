"""Command line entry points (server-side admin; the tenant here is chosen by the operator at the shell).

  python -m app.cli seed --tenant demo --pack packs/datacenter/topology.json [--reset]
  python -m app.cli stats --tenant demo
  python -m app.cli bootstrap --tenant demo [--reset]        create schema and the demo users
  python -m app.cli add-user --tenant demo --user op1 --role operator --password ...
  python -m app.cli investigate --tenant demo --incident INC-XXXXXX [--as operator1]

Carrying out a decision (each acts as a named user of that tenant; the user's role in the graph decides
what is allowed, exactly as for the API):
  python -m app.cli approve  --tenant demo --as operator2 --decision DEC-XXXXXXXX [--ttl 600] [--note ...]
  python -m app.cli reject   --tenant demo --as operator2 --decision DEC-XXXXXXXX [--reason ...]
  python -m app.cli execute  --tenant demo --as operator1 --decision DEC-XXXXXXXX
  python -m app.cli status   --tenant demo --as operator1 --decision DEC-XXXXXXXX
  python -m app.cli verify   --tenant demo --as operator1 --decision DEC-XXXXXXXX
  python -m app.cli rollback --tenant demo --as operator1 --decision DEC-XXXXXXXX [--reason ...]
  python -m app.cli replan   --tenant demo --as operator1 --decision DEC-XXXXXXXX
  python -m app.cli audit    --tenant demo --as operator1 --decision DEC-XXXXXXXX
Exit codes: 0 done, 2 FalkorDB unreachable, 3 refused (the reason is printed as JSON on stderr).
"""

import argparse
import json
import os
import secrets
import sys

from app.execution.service import ExecError
from app.graph.client import GraphUnavailable, TenantGraph, rows
from app.graph.importer import import_pack, load_pack
from app.graph.schema import ensure_schema

# One synthetic account per role, for practice mode.
DEMO_USERS = {"manager1": "manager", "operator1": "operator", "operator2": "operator", "staff1": "staff",
              "tech1": "tech", "tech2": "tech", "safety1": "authority", "meters1": "integration"}

DECISION_COMMANDS = ("approve", "reject", "execute", "status", "verify", "rollback", "replan", "audit")


def reset_graph(tg: TenantGraph) -> None:
    try:
        tg.delete()
    except GraphUnavailable:
        raise
    except Exception as e:  # graph may not exist yet
        if "empty key" not in str(e).lower() and "invalid graph" not in str(e).lower():
            raise


def bootstrap(tenant: str, password: str | None = None, reset: bool = False) -> dict:
    """Create the tenant graph's indexes and one demo user per role. Returns the users and password."""
    from app.api.auth import add_user

    tg = TenantGraph(tenant)
    if reset:
        reset_graph(tg)
    ensure_schema(tg)
    password = password or os.getenv("LEAKTRACE_DEMO_PASSWORD") or secrets.token_urlsafe(12)
    for user, role in DEMO_USERS.items():
        add_user(tg, user, role, password)
    return {"graph": tg.name, "users": DEMO_USERS, "password": password}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="leaktrace")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("seed", help="create indexes and load a topology pack into a tenant graph")
    s.add_argument("--tenant", required=True)
    s.add_argument("--pack", required=True)
    s.add_argument("--reset", action="store_true", help="delete the tenant graph first")
    st = sub.add_parser("stats", help="node and relationship counts for a tenant graph")
    st.add_argument("--tenant", required=True)
    b = sub.add_parser("bootstrap", help="create schema and one demo user per role")
    b.add_argument("--tenant", required=True)
    b.add_argument("--reset", action="store_true")
    u = sub.add_parser("add-user")
    u.add_argument("--tenant", required=True)
    u.add_argument("--user", required=True)
    u.add_argument("--role", required=True)
    u.add_argument("--password", required=True)
    inv = sub.add_parser("investigate", help="investigate one problem and commit a decision")
    inv.add_argument("--tenant", required=True)
    inv.add_argument("--incident", required=True)
    inv.add_argument("--as", dest="user", help="user who asks for the plan (default: the engine itself)")
    for cmd in DECISION_COMMANDS:
        c = sub.add_parser(cmd, help=f"{cmd} a committed decision")
        c.add_argument("--tenant", required=True)
        c.add_argument("--as", dest="user", required=True)
        c.add_argument("--decision", required=True)
        if cmd == "approve":
            c.add_argument("--ttl", type=int)
            c.add_argument("--note")
        if cmd in ("reject", "rollback"):
            c.add_argument("--reason")
    a = p.parse_args(argv)

    try:
        tg = TenantGraph(a.tenant)
        if a.cmd == "seed":
            if a.reset:
                reset_graph(tg)
            ensure_schema(tg)
            print(json.dumps({"graph": tg.name, **import_pack(tg, load_pack(a.pack))}))
        elif a.cmd == "stats":
            print(json.dumps(rows(tg.read("stats"))[0], default=dict))
        elif a.cmd == "bootstrap":
            print(json.dumps(bootstrap(a.tenant, reset=a.reset)))
        elif a.cmd == "add-user":
            from app.api.auth import add_user

            add_user(tg, a.user, a.role, a.password)
            print(json.dumps({"user": a.user, "role": a.role, "graph": tg.name}))
        elif a.cmd == "investigate":
            from app.execution import service as execution

            user, role = (a.user, _role_of(tg, a.user)) if a.user else ("cli", execution.SYSTEM)
            rec = execution.investigate(tg, a.incident, user, role)
            print(json.dumps({k: rec.get(k) for k in ("decision_id", "kind", "status", "summary", "chosen", "fallback",
                                                       "authority", "tool_sequence", "execution")}, default=str))
        elif a.cmd in DECISION_COMMANDS:
            print(json.dumps(_decision_command(tg, a), default=str, indent=2))
    except GraphUnavailable as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except Refused as e:
        print(json.dumps(e.args[0]), file=sys.stderr)
        return 3
    except ExecError as e:
        print(json.dumps({"error": e.code, "http_status": e.status, **e.detail}, default=str), file=sys.stderr)
        return 3
    return 0


class Refused(Exception):
    pass


def _role_of(tg: TenantGraph, user: str) -> str:
    found = rows(tg.read("user_get", {"id": user}))
    if not found:
        raise Refused({"error": "unknown_user", "user": user, "graph": tg.name})
    return found[0]["role"]


def _decision_command(tg: TenantGraph, a) -> dict | list:
    from app import permissions as perm
    from app.execution import service as execution

    role = _role_of(tg, a.user)
    try:
        if a.cmd in ("status", "audit") and role not in perm.VIEWERS:
            raise execution.Forbidden("role_not_allowed", role=role, action=a.cmd)
        if a.cmd == "approve":
            return execution.approve(tg, a.decision, a.user, role, ttl_s=a.ttl, note=a.note)
        if a.cmd == "reject":
            return execution.reject(tg, a.decision, a.user, role, a.reason)
        if a.cmd == "rollback":
            return execution.rollback(tg, a.decision, a.user, role, a.reason)
        if a.cmd == "status":
            return execution.status(tg, a.decision)
        if a.cmd == "audit":
            return execution.audit(tg, a.decision)
        return getattr(execution, a.cmd)(tg, a.decision, a.user, role)
    except execution.ExecError as e:
        raise Refused({"error": e.code, "http_status": e.status, **e.detail})


if __name__ == "__main__":
    sys.exit(main())
