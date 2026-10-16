# LeakTrace

LeakTrace helps operators deal with leaks in water and coolant networks. Reports and meter readings go into a FalkorDB graph. Agents then use graph queries and graph algorithms to:

- find the likely cause and what is affected
- test each valve plan for whether critical equipment still gets enough flow
- commit to one plan, then act within strict limits or ask a person for approval

> **Status: work in progress.** What runs today:
>
> - the graph model and a synthetic data-centre cooling network
> - a REST API with logins, where the customer is bound to the login token
> - report and reading intake
> - one full scenario (S1) from a leak alarm to a committed decision: suspects, flow checks for every plan, and how much the agent may do on its own
> - carrying a decision out in practice mode: approval by a second person (or auto mode for low-risk plans), ordered valve moves picked up by a simulated field crew, a check against fresh meter readings, and undo
> - six helpers (Intake, Investigator, Planner, Dispatcher, Checker, Record keeper) that hand work to each other only through task nodes in the graph
> - jobs for people with step-by-step field confirmation, an emergency path, earned autonomy within a manager's ceiling, and an incident report
>
> All of this is tested against a live FalkorDB. No real equipment is connected: the valves, meters and field crew are simulated. The helpers can choose their tools with a language model, but **no model has been run with them yet**: every result in this README comes from the fixed rule-based chooser described below. Still to come: answers with sources (Ask LeakTrace), conversation history, and the web app. This README only describes what runs.

Built for Graph Hacks 2026, Track 1: Agents That Act on Connected Data.

## Setup (local)

Requirements: Docker, Python 3.11+.

```bash
cp .env.example .env              # FalkorDB on host port 6380; set LEAKTRACE_SECRET and LEAKTRACE_DEMO_PASSWORD
docker compose up -d              # FalkorDB (pinned image) + browser UI on http://localhost:3000
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # Windows; on macOS/Linux use .venv/bin/...
.venv/Scripts/python -m pytest -q                  # needs FalkorDB running (~80 s)
```

Run scenario S1 end to end. It resets the `demo` customer, creates synthetic demo accounts, then sends every step through the REST API:

```bash
.venv/Scripts/python -m scenario_generator.run s1 --tenant demo --seed 7 --reset
```

Carry the decision out, with a simulated field crew and plant (all through the REST API):

```bash
.venv/Scripts/python -m scenario_generator.run s1 --tenant demo --seed 7 --reset --execute happy
# other cases: stuck_v09, stuck_v07, worker_dies, graph_changes, approval_expires
.venv/Scripts/python -m scenario_generator.run s5 --tenant demo --seed 7 --reset --execute auto
# low-risk leak handled automatically; passing_valve: the check fails and the plan is undone
```

Let the six helpers do the work instead of the fixed investigation:

```bash
.venv/Scripts/python -m scenario_generator.run s1 --tenant demo --seed 7 --reset --helpers approve
# also: s1 stuck_v09, s2 evidence, s5 auto, s5 passing_valve; --helper-process runs each helper round as a new process
.venv/Scripts/python -m app.agents.worker --tenant demo --chooser rules   # run the helpers until no step is open
```

Or run the API server and drive it over HTTP:

```bash
.venv/Scripts/python -m app.cli bootstrap --tenant demo --reset      # demo accounts, password from LEAKTRACE_DEMO_PASSWORD
.venv/Scripts/python -m uvicorn app.api.main:app --port 8000
.venv/Scripts/python -m scenario_generator.run s1 --tenant demo --seed 7 --base-url http://localhost:8000 --import-pack
```

The agent tool server (MCP, stdio) for one customer: `LEAKTRACE_TENANT=demo python -m app.mcp_server.server`.

## What happens in scenario S1

All data is synthetic. A leak starts on the row A branch pipe (`SEG-A1`). Then:

1. The leak sensor alarms and pressure drops at manifold A.
2. The row A inflow meter reads high by the leak amount.
3. A staff member reports "water dripping under Rack A1 in Row A".

The report text is matched against names and ids in the graph. It links to Rack A1 and Row A and joins the open problem in that zone.

The investigation then runs these steps. Each one is a graph query or algorithm, and each call is recorded in the graph:

| Step | Graph work | Result on the demo network |
|---|---|---|
| Find suspects | `q1_find_suspects` | SEG-A1 first: alarm on the pipe, pressure drop downstream |
| How sure are we | `segment_signals`, `reports_near_segment`, `flow_balance_for_segment` | 0.90 (high): leak alarm 0.35 + pressure drop 0.20 + meter imbalance 0.25 + report 0.10 |
| What is affected | `q2_trace_impact`, `q3_exposure`, `evidence_path` | Racks A1 (critical) and A2, their jobs and owning teams; powered equipment near the water |
| What we remember | `q4_recall_incidents` | Past problems and active facts on the same equipment |
| Possible plans | `boundary_valves`, `closed_valves` | Close any of V-01 / V-07, optionally open backup link V-09, or do nothing (7 plans) |
| Test each plan | `algo.maxFlow` under a temporary capacity per plan | See below |
| May it act alone? | `policy_for_zone`, `asset_flags`, `actions_recent_in_zone` | Needs approval (L3), with the reasons |
| Commit | `options_write`, `decision_write`, `decision_justify` | `Decision` linked to every plan, the chosen plan and its evidence |

Plan results (computed by `algo.maxFlow`; the numbers are checked by hand in `tests/test_s1_end_to_end.py`):

| Plan | Fails | Why |
|---|---|---|
| **Close V-01 + V-07, open V-09** | nothing (chosen) | Leak gets 0. Rack A1 and Rack B1 each get 20 (they need 20). The less critical racks share the rest, so their jobs are moved |
| Do nothing | leak cut off, live equipment near water | The leak keeps flowing |
| Close V-01, open V-09 | leak cut off | Water flows backwards through V-07 into the leak (40) |
| Close V-01 | critical rack supplied | Rack A1 gets 0 and its training job cannot move |
| Close V-01 + V-07 | critical rack supplied | Rack A1 gets 0 |

**Why it asks for approval:** two of the eight auto-mode conditions fail. Rack A1 (criticality 5) is above the policy ceiling of 3, and the plan needs 3 valve moves where the policy allows 2. For a low-risk leak (the pipe feeding Rack A2), the same engine chooses "close V-04" and all eight conditions pass (handled automatically). If a manager pauses auto mode, that case needs approval instead. All of this is tested.

**Weak evidence never leads to action.** Any of the following results in a request for an on-site check, with no plans tested:

- one alarm on its own
- one pressure drop on its own
- a report while the meters show balanced flow

## Carrying out a decision (practice mode)

A committed plan moves through these states. Each change is one conditional write in FalkorDB, together with an `AuditEvent` saying who did it, in which role, from which state to which, and why. If the write fails part-way, none of it is applied.

```
proposed -> approved -> executing -> verifying -> verified
                                  \-> failed      \-> failed
failed | verified -> rolling_back -> rolled_back (or rollback_failed)
also: rejected, superseded (a newer plan, or the graph changed), approved -> proposed (approval expired)
```

- **Who approves.** A plan that needs approval (L3) must be approved by an operator or manager, and not by the person who asked for it. Approvals expire after 30 minutes by default. A low-risk plan (L2) is approved by auto mode at the moment it runs. If a manager has paused auto mode by then, the plan needs a person's OK instead. A "people decide" plan (L4) is never executed.
- **Is the plan still valid?** The decision stores a snapshot and fingerprint of the graph it was computed on: valve states, criticality, link capacities, active facts, policy limits, sensor states and meter readings. Before anything moves, the snapshot is read again. If anything changed materially, execution is refused, the old plan is marked superseded, and a new plan is made that needs its own approval.
- **Valve moves.** Each move is a `Task` that a field crew member picks up with a lease (`POST /tasks/claim`) and reports on (`POST /tasks/{id}/result`).
  - Order: valves that open go first, then the ones that close. In S1 that is open V-09, close V-01, close V-07, so rack A1 never loses its supply.
  - Commands are absolute ("V-01 closed") and carry an idempotency key, so a retry never moves a valve twice.
  - If a worker disappears, the lease runs out and someone else finishes the step.
  - If a valve does not move, the plan stops. Undo or a new plan is offered, and the stuck valve is recorded as a fact so the new plan avoids it.
- **Checking the result.** After the last move, readings that arrived later are compared with what the plan expected:
  - the inflow meter on the leaking pipe reads 0 (at most 2)
  - each critical rack's meter still reads its required flow, within the tolerance
  - pressure is back to normal
  - the metered region around the pipe balances again
- **Undo.** Every move that was applied is reversed, newest first, back to the exact valve states and link capacities recorded when the plan started. A low-risk plan whose check fails is undone automatically.

| Case (`--execute`) | What happens |
|---|---|
| `happy` | Approved by a second operator; 3 moves; check passes: verified |
| `stuck_v09` | The backup valve does not open: stops at step 1, nothing to undo; the new plan cannot use V-09 and asks people to decide |
| `stuck_v07` | Two moves done, then V-07 does not close: both moves undone, every valve and link back exactly as before |
| `worker_dies` | A crew member moves a valve and vanishes; the lease runs out; a second crew member finishes; still 3 physical moves |
| `graph_changes` | The leak grows after approval: execution refused as stale, a new plan is made, approved and verified |
| `approval_expires` | The approval runs out before execution: back to proposed, approved again, verified |
| S5 `auto` | Low-risk leak: handled automatically, no person involved, verified |
| S5 `passing_valve` | The valve says it closed, but the meters show water still flowing: the check fails and the plan is undone automatically |

The simulated plant (`scenario_generator/plant.py`) works out flows with its own model, independent of the app. The check compares the app's plan with readings from that separate model, not with the app's own prediction. The app never imports the simulator; it only sees what arrives over REST.

## The helpers

A new problem gets an Intake step, which is a `Task` node in the graph. Six helpers pick up steps of their kind, use their own tools, and hand on by creating the next `Task`. They are linked by `HANDED_OFF_TO`, so the hand-off chain is read straight from the graph.

| Helper | Step | Tools | Hands on to |
|---|---|---|---|
| Intake | `triage` | look at the problem, suggested severity, set severity | Investigator |
| Investigator | `investigate` | find suspects, check a suspect, trace impact, recall memory | Planner, or asks for evidence |
| Planner | `plan` | read findings, list plans, test a plan (`algo.maxFlow`), commit | Dispatcher |
| Dispatcher | `dispatch` | decision status, start the plan, create jobs, wait for approval | Checker or Record keeper |
| Checker | `verify` | decision status, check the result, wait | Record keeper |
| Record keeper | `record` | decision status, update the playbook, write the incident report | (done) |

**Who chooses the tools.** A chooser picks each helper's next tool.

- With a language model (`LEAKTRACE_AGENT_CHOOSER=llm` and an Anthropic API key), the model sees the helper's plain instructions, its tools and every earlier result, and must call exactly one tool per turn.
- Without one, a fixed rule list per helper picks the tools. This is what all the tests and every number here use, and each step in the graph is labelled with the chooser that took it.

**Authority stays in code, whatever the chooser picks:**

- A helper can only call its own tools.
- The Investigator cannot pass weak evidence on. It must trace the impact and check memory first.
- The Planner cannot commit before testing every plan.
- Starting a plan goes through the same execution engine as for people: a plan that needs approval is refused until a person approves it.
- No helper can approve, reject, undo or change the auto-mode policy.
- A helper that does not finish within 30 tool calls hands its step to people.

Waiting steps wake up when their decision changes. That happens when a person approves, or when fresh readings arrive.

S1, S2 and S5 produce different tool sequences: S2 asks for evidence and never lists plans; S5 starts on its own. Because the helpers keep nothing in memory, a helper process can be stopped and restarted at any time. In the restart test, every helper process ends after a valve was found stuck, and a new process handling a new leak recalls that fact. The new plan then avoids the valve.

**Closing problems.** A verified fix closes the problem. A new problem opens only when a sensor goes into alarm. A sensor that stays wet does not reopen it.

**When an automatic plan fails its check:**

1. The valve it closed is recorded as possibly not sealing.
2. The plan is undone.
3. The problem is planned again, and the new plan always needs a person's OK.

**Emergency path.** If a plan has waited for approval longer than the policy allows, with a leak alarm and live equipment near the water, the smallest plan that stops the leak may run without approval. It must also be the committed plan, and:

- keep every critical rack supplied
- be reversible, with no stuck valves
- rest on enough confidence
- run while auto mode is not paused

It still goes through the stale-plan guard, and it always leaves a review item and a (simulated) notification. Otherwise it is refused and escalated.

**Earned autonomy.** A plan that worked on the same pipe section at least 3 times, with no failure, may run automatically on equipment one step more critical than the usual limit. It never goes above the manager's ceiling. Every such widening is on the audit trail.

**Jobs and the report.** The Dispatcher creates jobs from the plan:

- an inspection for the field crew
- moving or warning about jobs on racks that lose flow, for the owning team
- agreeing a plan with people, when no plan passes

The crew confirms each step and can report a valve that would not move; that becomes a fact for future plans. The Record keeper writes an incident report from the facts in the graph. The prose comes from a fixed template unless a language model is configured, and the report says which.

## Graph data model (current)

One graph per customer, named `lt_<tenant>`. Login checks the account in that customer's graph. After that, every request works on the customer named in the signed token, never one named in the request or by a model. All demo data is synthetic and tagged `source: 'synthetic'`.

| Nodes | Meaning |
|---|---|
| `Source`, `Junction`, `Segment`, `Valve`, `Consumer` | The flow network: a cooling unit, header and manifolds, pipe sections, valves (`state`, `normal_state`, `reversible`, `locked`), racks (`criticality`, `required_flow`) |
| `Zone`, `Sensor`, `Meter`, `PDU`, `Reading` | Location, leak and pressure sensors (`state`), flow meters (`value`), power feeds (`energised`), capped reading history |
| `Workload`, `Team`, `User` | Jobs on each rack (`criticality`, `migratable`), owning teams, login accounts (hashed passwords) |
| `AuthorityPolicy` | What helpers may do on their own: `min_confidence`, `max_auto_criticality`, `max_auto_operations`, `rate_limit_per_zone_per_hour`, `critical_min_criticality`, `frozen`, ... |
| `Report`, `Incident`, `Option`, `Decision`, `Task`, `Episode`, `Fact` | Reports, problems, plans with their checks, committed decisions (`status`, `requested_by`, graph `fingerprint`), work steps (evidence checks and valve moves with lease and idempotency key), a record of every tool call, learned facts (for example a valve reported stuck) |
| `Approval`, `Execution`, `Action`, `Verification`, `AuditEvent` | Who approved and until when; one run of a plan with the exact prior valve states; each valve change made; the check against fresh readings; one record per state change |
| `Agent`, `WorkOrder`, `Playbook`, `Review`, `IncidentReport` | A helper (role, chooser, last process); a job for people with its steps and confirmations; a plan that worked before on a section, with success and failure counts; an item a manager must review; the incident report (facts and prose) |

Every network node also has the label `Entity`, with an index on `id`.

| Relationship | Meaning |
|---|---|
| `(a)-[:FLOWS_TO {id, dir, cap_base, open_cap, valve_id}]->(b)` | Flow link. `dir:'normal'` is the designed direction. A two-way pipe also has a `dir:'reverse'` edge for backfeed. `cap_base` is the capacity now (0 behind a closed valve); `open_cap` is the capacity with its valve open |
| `ROUTED_THROUGH`, `LOCATED_IN`, `ADJACENT_TO`, `IN_ZONE` | Location |
| `MONITORS`, `MEASURES {direction}`, `OF` | Sensors and meters; a reading belongs to its instrument |
| `RUNS_ON`, `POWERED_BY`, `OWNS` | Dependencies and ownership |
| `ABOUT`, `PART_OF`, `INVOLVED` | A report is about things and part of a problem; a problem involves zones and assets |
| `HAS_OPTION`, `DECIDED`, `CHOSE {role}`, `OPERATES`, `JUSTIFIED_BY` | A problem's plans and decision; the chosen and fallback plans; valves a plan moves; the evidence behind a decision |
| `FOR`, `OF`, `SUPERSEDES` | A work step for a problem; an episode of a problem or an audit record of a decision; fact history, and a newer decision replacing an older one |
| `HANDED_OFF_TO`, `CLAIMED_BY`, `ON`, `DERIVED_FROM` | One helper step passing work to the next; which helper took a step; what a job is about; a job or playbook coming from a decision |
| `APPROVES`, `IMPLEMENTS`, `PART_OF`, `AUTHORIZED_BY`, `VERIFIES`, `EVIDENCED_BY` | Approval of a decision; an execution and its actions carry out a decision; valve-move steps and actions belong to an execution; an action is allowed by an approval or by the auto-mode policy; a check of a decision; a fact and the field report it came from |

## Key queries and algorithms

All query text lives in [`app/graph/queries/`](app/graph/queries/). Each query is saved by name, and its parameters are kept separately. Reads run through `GRAPH.RO_QUERY` with a timeout, so a read can never write.

| Query | What it does | Decision it drives |
|---|---|---|
| `q1_find_suspects` | Pipe sections in a zone with a leak alarm, ranked by alarms on the section and pressure anomalies downstream (open links only) | Where the leak probably is |
| `flow_balance_for_segment` | For every metered region containing a section: inflow minus downstream outflow | Whether water is going missing there (a balanced region contradicts a suspect) |
| `q2_trace_impact`, `evidence_path` | Racks downstream through open links, their jobs and owning teams, and the map path to each (multi-hop) | What is affected, who to tell, the path shown on the map |
| `q3_exposure` | Racks in the same or an adjacent zone, with their power feeds | Whether live equipment is at risk |
| `q4_recall_incidents` | Earlier problems on the same assets, their decisions, and active facts | Whether past experience changes the plan |
| `boundary_valves` | The first valves met walking out from a section in either direction | Which valves can cut the section off |
| `max_flow` (`algo.maxFlow`) | Maximum flow from the cooling unit to one target, under a plan's temporary capacities | Whether the leak gets 0; whether each critical rack (alone, then together) still gets its required flow; how much the others lose |
| `asset_flags` | Locked or irreversible valves, and active "stuck" facts | Whether a plan is feasible at all |
| `policy_for_zone`, `actions_recent_in_zone` | The active auto-mode policy and recent actions | How much the agent may do on its own |
| `bfs_reach` (`algo.bfs`) | Everything connected to a node by flow links | Connected reach |
| `chunk_search` (vector index) | Nearest text passages (score is cosine distance, lower is closer) | Answers with sources (later) |
| `task_claim`, `task_release_expired` | Conditional write so only one worker picks up a step; expired leases go back to open | Agent coordination |
| `world_snapshot` | Everything a plan depends on, in one read | Whether an approved plan is still valid when it is about to run |
| `decision_transition`, `approval_write`, `approval_expire` | Conditional state change plus its audit record | Who may move a plan forward, and when an approval runs out |
| `execution_start` | Starts a run only if the plan's valves are still in the expected state; creates the ordered valve-move steps | That the moves happen in order, from the state the plan assumed |
| `move_task_claim`, `move_tasks_release_expired` | Next open valve move for a crew member; leases that ran out | That a step is never done by two people, and is finished if someone disappears |
| `move_done`, `move_failed` | Applies a reported move (valve state, link capacities, `Action`, next step) or stops the plan (and records a stuck valve as a fact), each in one atomic write | What the graph believes about each valve |
| `flow_balance_for_segment`, `instruments_current`, `verification_write` | Readings after the moves, compared with the plan | Verified, or failed with the check that failed |
| `rollback_start` | Undo steps, newest first, back to the recorded prior state | Restoring the network after a failed or unwanted plan |
| `agent_task_claim`, `agent_task_finish`, `agent_tasks_wake` | A helper picks up a step; finishes it and creates the next ones; a waiting step wakes when its decision changes | The hand-off chain between helpers |
| `break_glass_candidates` | Plans waiting for approval that the emergency path has not looked at | Whether to act without approval |
| `playbook_get`, `playbook_record` | Successes and failures of a plan on a section | Earned autonomy |
| `work_orders_create`, `work_order_confirm`, `work_order_complete`, `fact_write` | Jobs from a decision; field confirmation; a valve reported stuck becomes a fact | What people must do; what later plans avoid |
| `incident_facts`, `incident_report_write` | Everything about one problem in one read | The incident report |

**What-if for a plan.** A plan is written as a temporary capacity property `cap_<planId>` on every flow link:

- closed valves get 0
- opened valves get `open_cap`
- links into a rack are capped at what the rack needs
- every other link keeps `cap_base`

`algo.maxFlow` then runs with that capacity property, and the property is removed afterwards. The property name is passed only inside a parameter map, never in query text.

**How sure we are** (`app/domain/confidence.py`) is a fixed formula over graph counts:

| Sign | Weight |
|---|---|
| Leak alarm on the section | 0.35 |
| Leak alarm elsewhere in the zone (only if none on the section) | 0.10 |
| Pressure anomaly downstream | 0.20 |
| Meter imbalance in the smallest metered region | 0.25 |
| First report | 0.10 |
| Second reporter | 0.10 |
| That region balanced (contradiction) | −0.30 |

With fewer than two kinds of sign, the score is capped at 0.40.

**What the agent may do on its own** (`app/domain/authority.py`). It acts only if all eight conditions hold:

1. An active policy covers the zone and auto mode is not paused.
2. The confidence is high enough and nothing contradicts it.
3. No critical rack loses flow.
4. Nothing affected is above the criticality ceiling.
5. Every valve move can be undone and none is locked or stuck.
6. The plan stays within the move limit and the zone's hourly action limit.
7. Nothing affects life safety.
8. An undo plan and a check are ready.

Otherwise the decision needs approval, and lists the conditions that failed.

## API (current)

`POST /auth/login` · `POST /assets/import` (manager) · `POST /reports` · `GET /reports/{code}` · `POST /readings` (meters account, field crew) · `GET /incidents` · `GET /incidents/{id}` · `POST /incidents/{id}/investigate` (operator, manager) · `GET /decisions/{id}` · `GET /agents/timeline?incident=`

Problems, helpers, jobs and reports: `POST /incidents/{id}/close` (operator, manager) · `GET /incidents/{id}/helpers` · `GET|POST /incidents/{id}/report` · `GET /work-orders` · `POST /work-orders/{id}/take|confirm|complete` (field crew) · `GET /reviews`

Carrying out a decision: `POST /decisions/{id}/approve` · `/reject` · `/execute` · `/verify` · `/rollback` · `/replan` (operator, manager) · `GET /decisions/{id}/status` · `GET /decisions/{id}/audit` · `POST /tasks/claim` · `POST /tasks/{id}/result` (field crew)

The same steps from the command line, acting as a named user of one customer (that user's role decides what is allowed):

```bash
.venv/Scripts/python -m app.cli approve --tenant demo --as operator2 --decision DEC-XXXXXXXX
.venv/Scripts/python -m app.cli status  --tenant demo --as operator1 --decision DEC-XXXXXXXX
# also: reject, execute, verify, rollback, replan, audit
```

The agent tool server adds one read-only tool, `execution_status`. No tool can approve, execute or undo anything.

With FalkorDB stopped, every route answers `503 graph_unavailable`. Nothing is cached.

## Tests

`pytest -q` runs 204 tests against the live FalkorDB (about 2.5 minutes). They cover:

- the docs max-flow example (13)
- the what-if checks
- Q1–Q4
- S1 across several seeds, with every plan and number checked by hand
- weak-evidence cases
- each auto-mode condition on its own
- the stop switch (FalkorDB unreachable: the API answers 503, the CLI exits with an error)
- the import guard (`app/` never imports the scenario generator or another graph library)
- token-bound customers (a token for one customer cannot read another; forged and expired tokens are refused)
- task claim races and lease expiry
- every legal and illegal state change, and the audit record each one leaves
- approvals: the requester cannot approve, wrong roles and other customers are refused, forged and expired tokens are refused, approvals expire
- pausing auto mode turns a low-risk plan into one that needs approval; a "people decide" plan never runs
- a repeated report never moves a valve twice; a crew member whose lease ran out cannot report
- the stale-plan guard (valve state, criticality or a stuck-valve fact changed after approval)
- undo restoring the exact prior state after a partial failure
- S1 carried out on seeds 1-5 (verified every time) and every case in the table above
- four FalkorDB behaviours the saved queries work around, pinned so a change is noticed
- the helpers: the hand-off chain through task nodes, each helper using only its own tools, refusals coming from code when a scripted chooser tries forbidden things, S1/S2/S5 tool sequences differing, recall after every helper process is restarted
- closing problems, a new alarm opening a new problem, the escalation after an automatic undo
- the emergency path (acts after the wait; refuses when paused, unsure, starving a critical rack or stale) and earned autonomy (never above the manager's ceiling; the policy is unchanged by the helpers)
- jobs with field confirmation, and the incident report
- the language-model chooser's messages, with a fake client (no model is called in tests)

`LEAKTRACE_KILLSWITCH_DOCKER=1 pytest tests/test_kill_switch.py` also stops the real container twice:

- after a full S1 run: the stored decision can no longer be read until the container restarts
- in the middle of carrying a plan out: nothing is reported as verified while FalkorDB is down, and after the restart the crew's retried report is applied once and the plan finishes

## AI assistance

This project is built with an AI coding assistant (Claude Code). Separately, the product's helpers can use a language model at run time to choose tools; that is optional, and every result in this README was produced without it. The team directs the design, reviews the code, and checks every result against a running FalkorDB.
