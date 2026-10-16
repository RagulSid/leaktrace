"""A simulated field crew member: picks up valve moves over REST, works the simulated valve, reports back.

It reaches the app only through POST /tasks/claim and POST /tasks/{id}/result, with its own login,
exactly like a real crew member's phone or a device gateway would.
"""


class FieldWorker:
    def __init__(self, session, user: str, plant, lease_s: int = 30):
        self.s, self.user, self.plant, self.lease_s = session, user, plant, lease_s
        self.log: list[dict] = []

    def claim(self) -> dict | None:
        return self.s.post("/tasks/claim", self.user, {"lease_s": self.lease_s})["task"]

    def work_one(self, *, die_after_command: bool = False) -> dict | None:
        """Claim one step and carry it out. With die_after_command the worker moves the valve and then
        disappears without reporting (its lease will run out)."""
        task = self.claim()
        if task is None:
            return None
        res = self.plant.command(task["idempotency_key"], task["valve"], task["target"])
        if die_after_command:
            self.log.append({"task": task["id"], "died": True, **res})
            return {"task": task, "died": True}
        body = {"idempotency_key": task["idempotency_key"], "outcome": "done" if res["ok"] else "failed",
                "observed_state": res["observed"], "reason": res.get("reason")}
        out = self.s.post(f"/tasks/{task['id']}/result", self.user, body)
        self.log.append({"task": task["id"], "valve": task["valve"], "target": task["target"], **res,
                         "status_after": out["status"]})
        return {"task": task, "report": body, "response": out}

    def drain(self, limit: int = 50) -> list[dict]:
        done = []
        for _ in range(limit):
            r = self.work_one()
            if r is None:
                break
            done.append(r)
        return done
