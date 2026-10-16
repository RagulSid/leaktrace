"""LeakTrace REST API. Run: uvicorn app.api.main:app

Every route that touches data works on the graph of the tenant in the caller's verified token.
If FalkorDB is unreachable every route answers 503: there is no cache and no fallback.
"""

from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.agents import investigate
from app.api.auth import Principal, login, require
from app.agents import runtime as helpers
from app.execution import incident_report, work_orders
from app.execution import service as execution
from app.graph.client import GraphUnavailable, rows
from app.graph.importer import import_pack
from app.graph.schema import ensure_schema
from app.intake.readings import BadReadings, ingest_readings
from app.intake.reports import UnknownAsset, ingest_report, report_status
from app.memory import episodic
from app.permissions import APPROVERS, DECIDERS, FIELD, REPORTERS, VIEWERS

app = FastAPI(title="LeakTrace", version="0.2.0")


@app.exception_handler(GraphUnavailable)
def _graph_down(_: Request, e: GraphUnavailable):
    return JSONResponse(status_code=503, content={"error": "graph_unavailable", "detail": str(e)})


@app.exception_handler(execution.ExecError)
def _refused(_: Request, e: execution.ExecError):
    return JSONResponse(status_code=e.status, content={"error": e.code, **e.detail})


class LoginIn(BaseModel):
    tenant: str
    username: str
    password: str


class ReportIn(BaseModel):
    text: str = Field(min_length=3, max_length=2000)
    asset_code: str | None = None
    hazard: bool = False
    source: str = "synthetic"


class ReadingIn(BaseModel):
    id: str
    ts: float
    value: float | None = None
    state: str | None = None


class ReadingsIn(BaseModel):
    readings: list[ReadingIn] = Field(min_length=1, max_length=500)
    source: str = "synthetic"


class ApproveIn(BaseModel):
    ttl_s: int | None = Field(default=None, ge=1)
    note: str | None = Field(default=None, max_length=500)


class ReasonIn(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class CloseIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ConfirmIn(BaseModel):
    step: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=500)


class CompleteIn(BaseModel):
    findings: str | None = Field(default=None, max_length=1000)
    stuck_valves: list[str] = Field(default_factory=list, max_length=20)


class ClaimIn(BaseModel):
    lease_s: int | None = Field(default=None, ge=1)


class ResultIn(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=200)
    outcome: Literal["done", "failed"]
    observed_state: Literal["open", "closed"] | None = None
    reason: str | None = Field(default=None, max_length=200)


@app.post("/auth/login")
def auth_login(body: LoginIn):
    out = login(body.tenant, body.username, body.password)
    if out is None:
        raise HTTPException(401, "wrong tenant, username or password")
    return out


@app.post("/assets/import")
def assets_import(pack: dict, p: Principal = Depends(require("manager"))):
    tg = p.graph()
    ensure_schema(tg)
    try:
        return import_pack(tg, pack)
    except (KeyError, ValueError) as e:
        raise HTTPException(422, f"bad pack: {e}")


@app.post("/reports")
def reports_create(body: ReportIn, p: Principal = Depends(require(*REPORTERS))):
    try:
        return ingest_report(p.graph(), text=body.text, reporter=p.user, asset_code=body.asset_code,
                             hazard=body.hazard, source=body.source)
    except UnknownAsset as e:
        raise HTTPException(422, f"unknown asset code {e}")


@app.get("/reports/{code}")
def reports_get(code: str, p: Principal = Depends(require(*REPORTERS))):
    out = report_status(p.graph(), code)
    if out is None:
        raise HTTPException(404, "no such report")
    return out


@app.post("/readings")
def readings_create(body: ReadingsIn, p: Principal = Depends(require("integration", "tech"))):
    tg = p.graph()
    try:
        out = ingest_readings(tg, [r.model_dump() for r in body.readings], source=body.source)
    except BadReadings as e:
        raise HTTPException(422, str(e))
    out["verifications"] = execution.on_readings(tg)  # plans waiting for fresh readings are checked now
    return out


@app.get("/incidents")
def incidents_list(p: Principal = Depends(require(*VIEWERS))):
    return rows(p.graph().read("incidents_list"))


@app.get("/incidents/{incident}")
def incidents_get(incident: str, p: Principal = Depends(require(*VIEWERS))):
    out = rows(p.graph().read("incident_get", {"id": incident}))
    if not out:
        raise HTTPException(404, "no such problem")
    return out[0]


@app.post("/incidents/{incident}/investigate")
def incidents_investigate(incident: str, p: Principal = Depends(require(*DECIDERS))):
    return execution.investigate(p.graph(), incident, p.user, p.role)


@app.post("/incidents/{incident}/close")
def incidents_close(incident: str, body: CloseIn, p: Principal = Depends(require(*DECIDERS))):
    return execution.close_problem(p.graph(), incident, p.user, p.role, body.reason)


@app.get("/incidents/{incident}/helpers")
def incidents_helpers(incident: str, p: Principal = Depends(require(*VIEWERS))):
    """The helpers' hand-off chain for one problem, read from the graph."""
    return helpers.chain(p.graph(), incident)


@app.get("/incidents/{incident}/report")
def incidents_report(incident: str, p: Principal = Depends(require(*VIEWERS))):
    out = incident_report.latest(p.graph(), incident)
    if out is None:
        raise HTTPException(404, "no report yet")
    return out


@app.post("/incidents/{incident}/report")
def incidents_report_write(incident: str, p: Principal = Depends(require(*DECIDERS))):
    tg = p.graph()
    if not rows(tg.read("incident_get", {"id": incident})):
        raise HTTPException(404, "no such problem")
    return incident_report.write(tg, incident, p.user)


@app.get("/work-orders")
def work_orders_list(incident: str | None = None, p: Principal = Depends(require(*VIEWERS, *FIELD))):
    return work_orders.list_for(p.graph(), p.role, incident)


@app.post("/work-orders/{wo}/take")
def work_orders_take(wo: str, p: Principal = Depends(require(*FIELD))):
    return work_orders.take(p.graph(), wo, p.user, p.role)


@app.post("/work-orders/{wo}/confirm")
def work_orders_confirm(wo: str, body: ConfirmIn, p: Principal = Depends(require(*FIELD))):
    return work_orders.confirm(p.graph(), wo, p.user, p.role, body.step, body.note)


@app.post("/work-orders/{wo}/complete")
def work_orders_complete(wo: str, body: CompleteIn, p: Principal = Depends(require(*FIELD))):
    return work_orders.complete(p.graph(), wo, p.user, p.role, body.findings, body.stuck_valves)


@app.get("/reviews")
def reviews_list(p: Principal = Depends(require(*VIEWERS))):
    return rows(p.graph().read("reviews_list"))


@app.get("/decisions/{decision}")
def decisions_get(decision: str, p: Principal = Depends(require(*VIEWERS))):
    out = investigate.get_decision(p.graph(), decision)
    if out is None:
        raise HTTPException(404, "no such decision")
    return out


@app.post("/decisions/{decision}/approve")
def decisions_approve(decision: str, body: ApproveIn | None = None, p: Principal = Depends(require(*APPROVERS))):
    body = body or ApproveIn()
    return execution.approve(p.graph(), decision, p.user, p.role, ttl_s=body.ttl_s, note=body.note)


@app.post("/decisions/{decision}/reject")
def decisions_reject(decision: str, body: ReasonIn | None = None, p: Principal = Depends(require(*APPROVERS))):
    return execution.reject(p.graph(), decision, p.user, p.role, (body or ReasonIn()).reason)


@app.post("/decisions/{decision}/execute")
def decisions_execute(decision: str, p: Principal = Depends(require(*DECIDERS))):
    return execution.execute(p.graph(), decision, p.user, p.role)


@app.get("/decisions/{decision}/status")
def decisions_status(decision: str, p: Principal = Depends(require(*VIEWERS))):
    return execution.status(p.graph(), decision)


@app.post("/decisions/{decision}/verify")
def decisions_verify(decision: str, p: Principal = Depends(require(*DECIDERS))):
    return execution.verify(p.graph(), decision, p.user, p.role)


@app.post("/decisions/{decision}/rollback")
def decisions_rollback(decision: str, body: ReasonIn | None = None, p: Principal = Depends(require(*DECIDERS))):
    return execution.rollback(p.graph(), decision, p.user, p.role, (body or ReasonIn()).reason)


@app.post("/decisions/{decision}/replan")
def decisions_replan(decision: str, p: Principal = Depends(require(*DECIDERS))):
    return execution.replan(p.graph(), decision, p.user, p.role)


@app.get("/decisions/{decision}/audit")
def decisions_audit(decision: str, p: Principal = Depends(require(*VIEWERS))):
    return execution.audit(p.graph(), decision)


@app.post("/tasks/claim")
def tasks_claim(body: ClaimIn | None = None, p: Principal = Depends(require(*FIELD))):
    task = execution.claim(p.graph(), p.user, p.role, (body or ClaimIn()).lease_s)
    return {"task": task}


@app.post("/tasks/{task}/result")
def tasks_result(task: str, body: ResultIn, p: Principal = Depends(require(*FIELD))):
    return execution.report(p.graph(), task, p.user, p.role, body.idempotency_key, body.outcome,
                            body.observed_state, body.reason)


@app.get("/agents/timeline")
def agents_timeline(incident: str, p: Principal = Depends(require(*VIEWERS))):
    return episodic.for_incident(p.graph(), incident)
