"""Ask LeakTrace routes: ask a question (answer with sources or "I don't know"), the saved conversation, asking the
field crew to find out, and reading documents, tickets and chats in (managers only)."""

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app import clock
from app.api.auth import Principal, require
from app.api.views import RateLimit
from app.brain import conversation
from app.brain.ask import ask
from app.brain.ingest import BadCorpus, ingest
from app.graph.client import TenantGraph, rows
from app.permissions import DECIDERS, REPORTERS, VIEWERS

router = APIRouter()
ask_limit = RateLimit(30)  # per address and minute: an answer may call a model


def _limit_ask(request: Request) -> None:
    ask_limit(request)  # looked up at call time


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    incident: str | None = Field(default=None, max_length=40)


class FindOutIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    incident: str | None = Field(default=None, max_length=40)
    target: str | None = Field(default=None, max_length=40)


def _problem(tg: TenantGraph, p: Principal, incident: str | None) -> str | None:
    if incident is None:
        return None
    if p.role not in VIEWERS:
        raise HTTPException(403, f"role {p.role} may not see problems")
    if not rows(tg.read("incident_get", {"id": incident})):
        raise HTTPException(404, "no such problem")
    return incident


@router.post("/brain/ask", dependencies=[Depends(_limit_ask)])
def brain_ask(body: AskIn, p: Principal = Depends(require(*REPORTERS))):
    tg = p.graph()
    incident = _problem(tg, p, body.incident)
    out = ask(tg, body.question)
    out["conversation"] = conversation.save_turn(tg, p.user, incident, body.question, out)
    return out


@router.get("/brain/conversation")
def brain_conversation(incident: str | None = None, p: Principal = Depends(require(*REPORTERS))):
    tg = p.graph()
    return conversation.history(tg, p.user, _problem(tg, p, incident))


@router.post("/brain/find-out")
def brain_find_out(body: FindOutIn, p: Principal = Depends(require(*DECIDERS))):
    """The "I don't know" offer: a job for the field crew to find out, on the asset if one was named."""
    tg = p.graph()
    incident = _problem(tg, p, body.incident)
    wid = "WO-" + secrets.token_hex(4).upper()
    out = rows(tg.write("brain_find_out_create", {
        "id": wid, "incident": incident, "target": body.target, "question": body.question, "ts": clock.now(),
        "actor": p.user, "steps": ["find out the answer", "write down what you found"]}))
    return {"work_order": out[0]["id"], "kind": "find_out"}


@router.post("/brain/ingest")
def brain_ingest(corpus: dict, p: Principal = Depends(require("manager"))):
    try:
        return ingest(p.graph(), corpus)
    except (BadCorpus, KeyError, TypeError, ValueError) as e:
        raise HTTPException(422, f"bad corpus: {e}")
