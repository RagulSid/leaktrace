"""Loader for saved Cypher queries. The .cypher files here are the only place query text lives.

Leading `//` comment lines document a query and are stripped; what `load()` returns is
exactly the text sent to FalkorDB (the client prepends a `CYPHER k=v ...` parameter header).
"""

from functools import cache
from pathlib import Path

_DIR = Path(__file__).parent


@cache
def load(name: str) -> str:
    path = _DIR / f"{name}.cypher"
    if path.parent != _DIR:
        raise ValueError(f"bad query name: {name!r}")
    lines = path.read_text(encoding="utf-8").splitlines()
    body = [ln for ln in lines if not ln.lstrip().startswith("//")]
    return "\n".join(body).strip()


def names() -> list[str]:
    return sorted(p.stem for p in _DIR.glob("*.cypher"))
