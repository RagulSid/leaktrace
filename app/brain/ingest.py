"""Read documents, maintenance tickets and shift chats into the customer's graph, next to the map.

No language model is involved. Every text is resolved against what is already on the map:
  - an exact id ("V-09", "SEG-A1", "TCK-1042") or an exact name ("Backup link valve") becomes a MENTIONS link;
  - a word that looks like a map id (a known prefix such as "V-") but matches nothing becomes a Review item for a
    manager, instead of silently entering the map;
  - each paragraph, ticket and message becomes a Chunk with a passage vector (app/brain/embed.py).
The Record keeper's rules for tickets (deterministic, from the ticket's problem code):
  - valve_failed_to_operate (not cancelled): an active 'stuck' Fact about the asset, evidenced by the ticket, so
    every later plan that moves that valve fails its "can be done" check and cites the fact;
  - valve_repaired: a 'working' Fact that SUPERSEDES every active 'stuck' fact about the asset (kept, never deleted).
Who knows what (EXPERT_IN) is recomputed from the tickets people did. Ingesting the same corpus twice changes
nothing (every write is a MERGE on a stable id).
"""

import json
import re
from datetime import datetime, timezone

from redis.exceptions import ResponseError

from app import clock, config
from app.brain.embed import embed
from app.graph.client import TenantGraph, rows

ID_TOKEN = re.compile(r"\b[A-Z]{1,5}-[A-Z0-9]+(?:-[A-Z0-9]+)*\b")
STUCK_CONFIDENCE = 0.8
WORKING_CONFIDENCE = 0.9


class BadCorpus(ValueError):
    pass


def _ts(day: str | None) -> float | None:
    if not day:
        return None
    d = datetime.fromisoformat(day)
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()


def ensure_index(tg: TenantGraph) -> None:
    try:
        tg.write("chunk_vector_index", {"dim": config.EMBED_DIM})
    except ResponseError as e:
        if "already indexed" not in str(e).lower():
            raise


class Resolver:
    """Ids and names on this customer's map, to find what a text talks about."""

    def __init__(self, tg: TenantGraph, extra_ids: set[str] = frozenset()):
        ents = rows(tg.read("brain_entities"))
        self.ids = {e["id"] for e in ents}
        self.labels = {e["id"]: e["labels"] for e in ents}
        self._name = {e["id"]: e.get("name") for e in ents}
        self.sources = {r["id"] for r in rows(tg.read("brain_source_ids"))} | set(extra_ids)
        self.prefixes = {i.split("-")[0] for i in self.ids if "-" in i}
        self.names = sorted(((e["name"].lower(), e["id"]) for e in ents if e.get("name") and len(e["name"]) >= 5),
                            key=lambda x: -len(x[0]))

    def name_of(self, eid: str) -> str:
        return self._name.get(eid) or eid

    def find(self, text: str, own_id: str | None = None) -> tuple[list[str], list[str]]:
        """(resolved ids in order of first appearance, unresolved id-like words)."""
        found, unresolved = [], []
        for tok in ID_TOKEN.findall(text.upper()):
            if tok == own_id:
                continue
            if tok in self.ids or tok in self.sources:
                found.append(tok)
            elif tok.split("-")[0] in self.prefixes:
                unresolved.append(tok)
        low = text.lower()
        for name, eid in self.names:
            if re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", low):
                found.append(eid)
        return list(dict.fromkeys(found)), list(dict.fromkeys(unresolved))


def ingest(tg: TenantGraph, corpus: dict) -> dict:
    source = corpus.get("source") or "synthetic"
    teams, people = corpus.get("teams") or [], corpus.get("people") or []
    docs, tickets, msgs = corpus.get("documents") or [], corpus.get("tickets") or [], corpus.get("messages") or []
    ensure_index(tg)
    on_map = {e["id"] for e in rows(tg.read("brain_entities"))}
    for t in tickets:
        if t["asset"] not in on_map:
            raise BadCorpus(f"ticket {t['id']} is on {t['asset']}, which is not on the map")

    out = {"teams": 0, "people": 0, "owns": 0, "documents": 0, "tickets": 0, "messages": 0, "chunks": 0,
           "mentions": 0, "reviews": 0, "facts": [], "superseded": [], "experts": 0}
    p = {"source": source}
    if teams:
        out["teams"] = rows(tg.write("brain_teams_upsert", {**p, "rows": teams}))[0]["n"]
    if people:
        out["people"] = rows(tg.write("brain_people_upsert", {**p, "rows": people}))[0]["n"]
    owns = [{"team": o["team"], "asset": a} for o in corpus.get("ownership") or [] for a in o["assets"]]
    if owns:
        out["owns"] = rows(tg.write("brain_owns_upsert", {**p, "rows": owns}))[0]["n"]
    if docs:
        out["documents"] = rows(tg.write("brain_documents_upsert", {**p, "rows": [
            {"id": d["id"], "kind": d["kind"], "title": d["title"], "owner": d.get("owner"),
             "reviewed_at": _ts(d.get("reviewed_on"))} for d in docs]}))[0]["n"]
    if tickets:
        out["tickets"] = rows(tg.write("brain_tickets_upsert", {**p, "rows": [
            {**{k: t.get(k) for k in ("id", "asset", "problem_code", "status", "performed_by", "title", "text")},
             "opened_at": _ts(t.get("opened_on")), "closed_at": _ts(t.get("closed_on"))} for t in tickets]}))[0]["n"]
    if msgs:
        out["messages"] = rows(tg.write("brain_messages_upsert", {**p, "rows": [
            {"id": m["id"], "channel": m["channel"], "author": m.get("author"), "text": m["text"],
             "ts": _ts(m.get("sent_on"))} for m in msgs]}))[0]["n"]

    # passages, mentions and the names that match nothing
    res = Resolver(tg, {d["id"] for d in docs} | {t["id"] for t in tickets})  # after the teams: their names count
    chunks, mentions, reviews = [], [], []
    texts = ([(d["id"], d["title"], d["text"]) for d in docs] + [(t["id"], t["title"], [t["text"]]) for t in tickets]
             + [(m["id"], None, [m["text"]]) for m in msgs])
    for sid, title, paras in texts:
        for i, para in enumerate(paras):
            chunks.append({"id": f"{sid}#{i + 1}", "source_id": sid, "text": para, "embedding": embed(para)})
        found, unresolved = res.find(" ".join(([title] if title else []) + list(paras)), own_id=sid)
        mentions += [{"source_id": sid, "target": x} for x in found]
        reviews += [{"id": f"REV-M-{sid}-{u}", "source_id": sid, "reason": "unresolved_mention",
                     "detail": json.dumps({"word": u, "source": sid})} for u in unresolved]
    if chunks:
        out["chunks"] = rows(tg.write("brain_chunks_upsert", {**p, "rows": chunks}))[0]["n"]
    if mentions:
        out["mentions"] = rows(tg.write("brain_mentions_upsert", {**p, "rows": mentions}))[0]["n"]
    if reviews:
        out["reviews"] = rows(tg.write("brain_review_mention", {**p, "rows": reviews, "ts": clock.now()}))[0]["n"]

    # the Record keeper's ticket rules, oldest ticket first so a repair after a failure replaces it
    for t in sorted(tickets, key=lambda t: _ts(t.get("opened_on")) or 0):
        code, asset = t.get("problem_code"), t["asset"]
        ts = _ts(t.get("closed_on")) or _ts(t.get("opened_on")) or clock.now()
        if code == "valve_failed_to_operate" and t.get("status") != "cancelled":
            row = {"ticket": t["id"], "asset": asset, "fact": f"F-{t['id']}", "kind": "stuck", "ts": ts,
                   "confidence": STUCK_CONFIDENCE, "statement": f"{asset} did not move: {t['title']} (ticket {t['id']})"}
            out["facts"] += [r["id"] for r in rows(tg.write("brain_fact_from_ticket", {**p, "rows": [row]}))]
        elif code == "valve_repaired":
            fid = f"F-{t['id']}"
            old = [r["id"] for r in rows(tg.read("brain_active_stuck", {"asset": asset}))]
            row = {"ticket": t["id"], "asset": asset, "fact": fid, "kind": "working", "ts": ts,
                   "confidence": WORKING_CONFIDENCE, "statement": f"{asset} works again: {t['title']} (ticket {t['id']})"}
            out["facts"] += [r["id"] for r in rows(tg.write("brain_fact_from_ticket", {**p, "rows": [row]}))]
            if old:
                out["superseded"] += rows(tg.write("brain_fact_supersede", {"fact": fid, "old": old, "ts": ts}))[0]["ids"]
    out["experts"] = rows(tg.write("brain_expertise_refresh"))[0]["n"]
    return out
