"""app/ must not import the scenario generator or any second graph library."""

import ast
from pathlib import Path

from tests.conftest import ROOT

# no second graph library, and no vendor LLM SDK: models are reached only through app/agents/llm_client.py
FORBIDDEN = {"scenario_generator", "networkx", "igraph", "rustworkx", "graph_tool", "anthropic", "openai"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


def test_app_has_no_forbidden_imports():
    files = sorted((ROOT / "app").rglob("*.py"))
    assert len(files) > 20
    bad = {str(f.relative_to(ROOT)): sorted(_imports(f) & FORBIDDEN) for f in files}
    assert {k: v for k, v in bad.items() if v} == {}


PRIVATE = ["repo" + "-docs", "docs/" + "AI_DISCLOSURE", "docs/" + "EVALUATION"]  # built from parts on purpose


def test_app_never_mentions_private_folders():
    for f in (ROOT / "app").rglob("*"):
        if f.is_file() and f.suffix in {".py", ".cypher", ".json"}:
            text = f.read_text(encoding="utf-8")
            assert not [p for p in PRIVATE if p in text], f
