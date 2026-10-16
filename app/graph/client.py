"""FalkorDB connection and the tenant-bound graph handle every other module uses.

Reads go through GRAPH.RO_QUERY with a timeout, so a saved read can never write.
Every call is timed and kept in a small in-process log. The log keeps the saved query name,
its text and its parameters as separate fields (the How it works page shows them side by side;
the client itself sends them as a `CYPHER k=v ...` header in front of the text).
"""

import time
from collections import deque
from dataclasses import dataclass, field
from functools import cache

from falkordb import FalkorDB
from falkordb.query_result import QueryResult
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from app import config
from app.graph import queries
from app.graph.tenancy import graph_name


class GraphUnavailable(RuntimeError):
    """FalkorDB cannot be reached. Nothing falls back to a cache: callers must fail loudly."""


@dataclass
class QueryLogEntry:
    graph: str
    query: str  # saved query name
    text: str  # saved query text, exactly as loaded from app/graph/queries
    params: dict = field(default_factory=dict)
    mode: str = "read"  # "read" | "write"
    ms: float = 0.0
    rows: int = 0
    error: str | None = None


QUERY_LOG: deque[QueryLogEntry] = deque(maxlen=500)
_MAX_LOGGED_PARAM_CHARS = 2000


def _loggable(params: dict | None) -> dict:
    out = {}
    for k, v in (params or {}).items():
        s = repr(v)
        out[k] = v if len(s) <= _MAX_LOGGED_PARAM_CHARS else s[:_MAX_LOGGED_PARAM_CHARS] + "..."
    return out


@cache
def _connect() -> FalkorDB:
    return FalkorDB(
        host=config.FALKORDB_HOST,
        port=config.FALKORDB_PORT,
        password=config.FALKORDB_PASSWORD,
        socket_connect_timeout=3,
    )


def get_db() -> FalkorDB:
    """The FalkorDB client already talks to the server in its constructor (sentinel/cluster check)."""
    try:
        return _connect()
    except (RedisConnectionError, RedisTimeoutError, OSError) as e:
        raise GraphUnavailable(
            f"FalkorDB is not reachable at {config.FALKORDB_HOST}:{config.FALKORDB_PORT} ({e})"
        ) from e


get_db.cache_clear = _connect.cache_clear


class TenantGraph:
    """A handle on one tenant's graph. Query text comes only from app/graph/queries/*.cypher."""

    def __init__(self, tenant: str, db: FalkorDB | None = None):
        self.tenant = tenant
        self.name = graph_name(tenant)
        self._g = (db or get_db()).select_graph(self.name)

    def read(self, query_name: str, params: dict | None = None, timeout_ms: int | None = None) -> QueryResult:
        return self._run(query_name, queries.load(query_name), params, "read", timeout_ms or config.READ_TIMEOUT_MS)

    def write(self, query_name: str, params: dict | None = None) -> QueryResult:
        return self._run(query_name, queries.load(query_name), params, "write", None)

    def write_text(self, query_name: str, text: str, params: dict | None = None) -> QueryResult:
        """For the few templated statements (labels or relationship types filled from an allowlist)."""
        return self._run(query_name, text, params, "write", None)

    def explain(self, query_name: str, params: dict | None = None):
        return self._g.explain(queries.load(query_name), params)

    def profile_read(self, query_name: str, params: dict | None = None):
        # GRAPH.PROFILE executes the query, writes included; only call it on saved read-only queries.
        return self._g.profile(queries.load(query_name), params)

    def slowlog(self):
        return self._g.slowlog()

    def delete(self) -> None:
        self._g.delete()

    def _run(self, name, text, params, mode, timeout_ms) -> QueryResult:
        t0 = time.perf_counter()
        entry = QueryLogEntry(self.name, name, text, _loggable(params), mode)
        try:
            if mode == "read":
                res = self._g.ro_query(text, params, timeout=timeout_ms)
            else:
                res = self._g.query(text, params)
        except (RedisConnectionError, RedisTimeoutError, OSError) as e:
            entry.ms, entry.error = (time.perf_counter() - t0) * 1000, f"graph unavailable: {e}"
            QUERY_LOG.append(entry)
            raise GraphUnavailable(
                f"FalkorDB is not reachable at {config.FALKORDB_HOST}:{config.FALKORDB_PORT} ({e})"
            ) from e
        except Exception as e:
            entry.ms, entry.error = (time.perf_counter() - t0) * 1000, str(e)
            QUERY_LOG.append(entry)
            raise
        entry.ms, entry.rows = (time.perf_counter() - t0) * 1000, len(res.result_set)
        QUERY_LOG.append(entry)
        return res


def rows(res: QueryResult) -> list[dict]:
    """Result set as a list of dicts keyed by column name."""
    cols = [h[1] if isinstance(h, (list, tuple)) else h for h in res.header]
    cols = [c.decode() if isinstance(c, bytes) else c for c in cols]
    return [dict(zip(cols, r)) for r in res.result_set]
