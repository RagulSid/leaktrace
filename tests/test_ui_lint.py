"""Lints for the web app and public text (BUILD_PROMPT 14.1, 14.2 and 16 tests 15 and 17).

  plain language  copy.ts holds every UI string; outside "details" and "howItWorks" no technical word appears
  no stray words  screens contain no hard-coded text: words come from copy.ts
  style           colours only in theme.css; no font weight above 600; at most one primary button per view
  public wording  no committed text names other tracks (the phrases are built from parts here on purpose)
"""

import json
import re
from pathlib import Path

import pytest

from tests.conftest import ROOT

WEB = ROOT / "web" / "src"
EXEMPT = {"details", "howItWorks"}

BANNED = [  # BUILD_PROMPT 14.1, left column, as whole words (with plurals)
    "incidents?", "segments?", "manifolds?", "cdus?", "cross-connects?", "consumers?", "blast radius", "options?",
    "constraints?", "authority", "envelopes?", "polic(y|ies)", "autonomy", "l2", "l3", "l4", "break-glass",
    "rollbacks?", "verifications?", "work orders?", "technicians?", "simulated", "synthetic", "triage", "verifier",
    "librarian", "facts?", "playbooks?", "episodes?", "memory browser", "brain", "tasks?", "claims?", "leases?",
    "hand-offs?", "tool calls?", "graphs?", "nodes?", "edges?", "cypher", "quer(y|ies)", "mcp", "schemas?",
    "tenants?", "vectors?", "embeddings?", "ingest", "latency", "confidence",
]


def copy_object() -> dict:
    text = (WEB / "copy.ts").read_text(encoding="utf-8")
    start = text.index("export const copy = ") + len("export const copy = ")
    end = text.index("} as const;") + 1
    return json.loads(text[start:end])


def strings(node, path=()):
    if isinstance(node, str):
        yield path, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from strings(v, path + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from strings(v, path + (str(i),))


def test_copy_is_plain_language():
    bad = []
    for path, s in strings(copy_object()):
        if path[0] in EXEMPT:
            continue
        for w in BANNED:
            if re.search(rf"(?<![\w-]){w}(?![\w-])", s, re.IGNORECASE):
                bad.append((".".join(path), w, s))
    assert bad == []


def test_copy_lint_catches_a_banned_word():
    assert any(re.search(rf"(?<![\w-]){w}(?![\w-])", "Approve this incident", re.IGNORECASE) for w in BANNED)


def tsx_files():
    return sorted(p for p in WEB.rglob("*.tsx"))


def test_screens_have_no_hard_coded_words():
    bad = []
    for f in tsx_files():
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r">([^<>{}]*)<", src):  # JSX text between tags (not TypeScript generics)
            text = m.group(1).strip()
            if re.fullmatch(r"[A-Za-z][A-Za-z '’.!?-]*", text) and not re.fullmatch(r"(string|number|boolean|any|unknown|Promise)", text):
                bad.append((f.name, text))
        for m in re.finditer(r'\b(placeholder|aria-label|title|alt)="([^"]*[A-Za-z][^"]*)"', src):
            bad.append((f.name, m.group(0)))
    assert bad == []


def test_colours_only_in_theme_css():
    bad = []
    for f in sorted(WEB.rglob("*")):
        if f.suffix not in {".ts", ".tsx", ".css"} or f.name == "theme.css":
            continue
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", src):
            bad.append((f.name, m.group(0)))
    assert bad == []


def test_no_font_weight_above_600():
    bad = []
    for f in sorted(WEB.rglob("*")):
        if f.suffix not in {".ts", ".tsx", ".css"}:
            continue
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r"font-?[wW]eight\"?\s*[:=]\s*\"?(\w+)", src):
            v = m.group(1)
            if v == "bold" or (v.isdigit() and int(v) > 600):
                bad.append((f.name, m.group(0)))
    assert bad == []
    theme = (WEB / "theme.css").read_text(encoding="utf-8")
    assert re.search(r"b,\s*strong\s*\{[^}]*font-weight:\s*600", theme), "<b> must not fall back to the browser's 700"


@pytest.mark.parametrize("view", sorted(p.name for p in (WEB / "views").glob("*.tsx")))
def test_at_most_one_primary_button_per_view(view):
    src = (WEB / "views" / view).read_text(encoding="utf-8")
    assert src.count("btn primary") <= 1


PHRASES = ["Track" + " 2", "Track" + " 3", "track" + " gate", "company" + " brain", "agent memory" + " and coordination"]


def test_public_text_names_no_other_track():
    places = [ROOT / "README.md", *WEB.rglob("*.ts*"), *WEB.rglob("*.css"), *(ROOT / "app").rglob("*.py"),
              *(ROOT / "app").rglob("*.cypher"), *(ROOT / "scenario_generator").rglob("*.py"),
              *(ROOT / "tests").rglob("*.py"), *(ROOT / "deploy").rglob("*"), *(ROOT / "tools").rglob("*.py")]
    bad = []
    for f in places:
        if f.is_file():
            text = f.read_text(encoding="utf-8", errors="ignore").lower()
            bad += [(str(f.relative_to(ROOT)), p) for p in PHRASES if p.lower() in text]
    assert bad == []


def test_ask_leaktrace_answer_sentences_are_plain_language():
    from app.brain.ask import CHOICE, SAY, TICKET_STATUS

    bad = [(k, w) for k, s in {**SAY, **CHOICE, **TICKET_STATUS}.items() for w in BANNED
           if re.search(rf"(?<![\w-]){w}(?![\w-])", s, re.IGNORECASE)]
    assert bad == []
