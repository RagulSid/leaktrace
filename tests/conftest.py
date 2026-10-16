import os

# Tests run against a local FalkorDB: a short connect timeout makes the FalkorDB-down tests fail fast
# (on Windows a refused connection otherwise takes about 2 s per attempt). Subprocesses inherit it.
os.environ.setdefault("FALKORDB_CONNECT_TIMEOUT_S", "0.5")

import uuid
from pathlib import Path

import pytest

from app.graph.client import TenantGraph
from app.graph.importer import import_pack, load_pack
from app.graph.schema import ensure_schema

ROOT = Path(__file__).resolve().parents[1]
DATACENTER_PACK = ROOT / "packs" / "datacenter" / "topology.json"


def fresh_tenant() -> str:
    return "t_" + uuid.uuid4().hex[:12]


@pytest.fixture
def make_graph():
    """Factory for throwaway tenant graphs, deleted after the test."""
    made = []

    def _make(pack: dict | None = None) -> TenantGraph:
        tg = TenantGraph(fresh_tenant())
        made.append(tg)
        ensure_schema(tg)
        if pack is not None:
            import_pack(tg, pack)
        return tg

    yield _make
    for tg in made:
        try:
            tg.delete()
        except Exception:
            pass


@pytest.fixture
def dc(make_graph) -> TenantGraph:
    """A fresh tenant graph loaded with the synthetic data-centre pack."""
    return make_graph(load_pack(DATACENTER_PACK))
