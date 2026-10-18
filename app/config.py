"""Settings read from the environment (and a local .env file if present).

Every threshold the engine uses lives here, with its environment variable. Policy limits that a manager
sets (min_confidence, max_auto_criticality, break_glass_wait_s, auto_promotion_ceiling, ...) are not here:
they are properties of the AuthorityPolicy node in the graph.
"""

import os
import secrets

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


# ---------------------------------------------------------------- connection and security
# 127.0.0.1, not "localhost": on this machine "localhost" tries IPv6 first and that attempt hangs until the
# connect timeout, on every new connection (measured: 3.0 s with a 3 s timeout, 0.015 s with 127.0.0.1).
FALKORDB_HOST = os.getenv("FALKORDB_HOST", "127.0.0.1")
FALKORDB_PORT = _int("FALKORDB_PORT", 6380)
FALKORDB_PASSWORD = os.getenv("FALKORDB_PASSWORD") or None
# How long to wait for a TCP connection to FalkorDB before failing (seconds).
FALKORDB_CONNECT_TIMEOUT_S = _float("FALKORDB_CONNECT_TIMEOUT_S", 3.0)
DEMO_TENANT = os.getenv("LEAKTRACE_DEMO_TENANT", "demo")
# Practice accounts of the demo customer. The shared password (operator, field crew, staff, safety officer) is public
# by design: the sign-in screen shows it so judges can get in. The manager and the meters account use a separate,
# private password: only a manager can change auto-mode limits or reset the practice data.
DEMO_PASSWORD = os.getenv("LEAKTRACE_DEMO_PASSWORD") or None
MANAGER_PASSWORD = os.getenv("LEAKTRACE_MANAGER_PASSWORD") or None
SHOW_PRACTICE_PASSWORD = os.getenv("LEAKTRACE_SHOW_PRACTICE_PASSWORD", "1") == "1"
# What ensure-demo runs to tell the practice story on an empty demo graph (a command, set by whoever runs the
# server; the app never imports the scenario generator). Empty: only the accounts and the practice map.
DEMO_SEED_COMMAND = os.getenv("LEAKTRACE_DEMO_SEED_COMMAND", "python -m scenario_generator.demo --tenant {tenant}")

# Every read gets a server-side timeout so a bad query cannot hang a request.
READ_TIMEOUT_MS = _int("LEAKTRACE_READ_TIMEOUT_MS", 2000)

# Token signing secret. Without one, a random secret is made per process (tokens die on restart).
SECRET = os.getenv("LEAKTRACE_SECRET") or secrets.token_hex(32)
SECRET_IS_EPHEMERAL = not os.getenv("LEAKTRACE_SECRET")
TOKEN_TTL_S = _int("LEAKTRACE_TOKEN_TTL_S", 12 * 3600)

# ---------------------------------------------------------------- intake
READING_HISTORY = _int("LEAKTRACE_READING_HISTORY", 50)  # readings kept per instrument
SEVERITY_HIGH_CRITICALITY = _int("LEAKTRACE_SEVERITY_HIGH_CRITICALITY", 4)  # zone holds something this critical
SEVERITY_MEDIUM_CRITICALITY = _int("LEAKTRACE_SEVERITY_MEDIUM_CRITICALITY", 2)

# ---------------------------------------------------------------- evidence (confidence formula thresholds)
BALANCE_TOLERANCE_ABS = _float("LEAKTRACE_BALANCE_TOLERANCE_ABS", 2.0)  # tolerance = max(abs, frac * flow)
BALANCE_TOLERANCE_FRAC = _float("LEAKTRACE_BALANCE_TOLERANCE_FRAC", 0.05)
SINGLE_KIND_CAP = _float("LEAKTRACE_SINGLE_KIND_CAP", 0.40)  # score cap with fewer than two kinds of sign
CONTRADICTION_PENALTY = _float("LEAKTRACE_CONTRADICTION_PENALTY", 0.30)
CONFIDENCE_HIGH = _float("LEAKTRACE_CONFIDENCE_HIGH", 0.75)  # "High" from here
CONFIDENCE_MEDIUM = _float("LEAKTRACE_CONFIDENCE_MEDIUM", 0.50)
DEFAULT_MIN_CONFIDENCE = _float("LEAKTRACE_DEFAULT_MIN_CONFIDENCE", 0.7)  # only when no policy applies
AMBIGUITY_MARGIN = _float("LEAKTRACE_AMBIGUITY_MARGIN", 0.10)  # two suspects this close: ask for evidence
MAX_SUSPECTS_ASSESSED = _int("LEAKTRACE_MAX_SUSPECTS_ASSESSED", 3)

# ---------------------------------------------------------------- plans and authority
MAX_BOUNDARY_VALVES = _int("LEAKTRACE_MAX_BOUNDARY_VALVES", 4)
MAX_BACKUP_VALVES = _int("LEAKTRACE_MAX_BACKUP_VALVES", 3)
DEFAULT_CRITICAL_MIN = _int("LEAKTRACE_DEFAULT_CRITICAL_MIN", 4)  # only when no policy applies
RATE_WINDOW_S = _int("LEAKTRACE_RATE_WINDOW_S", 3600)  # window for the policy's per-zone action limit

# ---------------------------------------------------------------- execution
# An approval is valid for at most APPROVAL_TTL_S (an approver may choose a shorter time).
APPROVAL_TTL_S = _int("LEAKTRACE_APPROVAL_TTL_S", 30 * 60)
# Lease a field worker holds on a valve move; after it runs out the step goes back to open.
DEFAULT_LEASE_S = _int("LEAKTRACE_LEASE_S", 60)
MAX_LEASE_S = _int("LEAKTRACE_MAX_LEASE_S", 600)
# A step whose lease ran out this many times is abandoned and the execution fails.
MOVE_MAX_ATTEMPTS = _int("LEAKTRACE_MOVE_MAX_ATTEMPTS", 3)
# How long verification waits for fresh readings when the policy sets no verify_window_s.
VERIFY_WINDOW_S = _int("LEAKTRACE_VERIFY_WINDOW_S", 120)
# Verification: what a cut-off section's inflow meter may still show (meter noise).
ISOLATION_MAX_FLOW = _float("LEAKTRACE_ISOLATION_MAX_FLOW", 2.0)
# Confidence written on a fact from a field report that a valve did not move.
STUCK_FACT_CONFIDENCE = _float("LEAKTRACE_STUCK_FACT_CONFIDENCE", 0.8)
# Confidence of a fact written when an automatic plan failed its check after closing exactly one valve.
NOT_SEALING_FACT_CONFIDENCE = _float("LEAKTRACE_NOT_SEALING_FACT_CONFIDENCE", 0.6)

# ---------------------------------------------------------------- break-glass and earned autonomy
# Used only when the policy node does not set them.
BREAK_GLASS_WAIT_S = _int("LEAKTRACE_BREAK_GLASS_WAIT_S", 300)
MIN_PLAYBOOK_SUCCESSES = _int("LEAKTRACE_MIN_PLAYBOOK_SUCCESSES", 3)

# ---------------------------------------------------------------- helpers (agents)
# "model": choose tools with a language model behind an OpenAI-compatible chat API; "rules": the fixed offline
# chooser; "auto": the model when LLM_BASE_URL, LLM_API_KEY and LLM_MODEL are all set, otherwise the rules.
AGENT_CHOOSER = os.getenv("LEAKTRACE_AGENT_CHOOSER", "auto")
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or None  # e.g. https://generativelanguage.googleapis.com/v1beta/openai
LLM_API_KEY = os.getenv("LLM_API_KEY") or None
LLM_MODEL = os.getenv("LLM_MODEL") or None
LLM_MAX_TOKENS = _int("LEAKTRACE_LLM_MAX_TOKENS", 2048)
# Thinking models (Gemini Flash) think before answering unless told not to: "low" answered a one-word prompt in
# 4.7 s versus 11.6 s by default (measured 2026-10-16). Empty: the parameter is not sent.
LLM_REASONING_EFFORT = os.getenv("LEAKTRACE_LLM_REASONING_EFFORT") or None
LLM_TIMEOUT_S = _float("LEAKTRACE_LLM_TIMEOUT_S", 8.0)  # per model call; a timeout hands the run to the rules
LLM_MAX_CALLS_PER_RUN = _int("LEAKTRACE_LLM_MAX_CALLS_PER_RUN", 60)  # model calls per helper run, then the rules
AGENT_MAX_STEPS = _int("LEAKTRACE_AGENT_MAX_STEPS", 30)  # tool calls per task before it is handed to people
AGENT_LEASE_S = _int("LEAKTRACE_AGENT_LEASE_S", 120)
AUTO_TRIAGE = os.getenv("LEAKTRACE_AUTO_TRIAGE", "1") == "1"  # a new problem gets an Intake step

# ---------------------------------------------------------------- Ask LeakTrace (answers with sources)
# Passage vectors: "hash" = hashed word counts computed here (no model, no network; finds passages that share
# words, not meaning). The vector index dimension must match EMBED_DIM.
EMBED_PROVIDER = os.getenv("LEAKTRACE_EMBED", "hash")
EMBED_DIM = _int("LEAKTRACE_EMBED_DIM", 256)
# Who words the answer: "template" (fixed sentences), "model" (the chat model above rewrites the template answer;
# its citations are checked), "auto" (the model when LLM_* are all set, otherwise templates).
ASK_PHRASER = os.getenv("LEAKTRACE_ASK_PHRASER", "auto")
ASK_PASSAGE_MAX_DISTANCE = _float("LEAKTRACE_ASK_PASSAGE_MAX_DISTANCE", 0.8)  # cosine distance; lower is closer
ASK_PASSAGE_MIN_SHARED_WORDS = _int("LEAKTRACE_ASK_PASSAGE_MIN_SHARED_WORDS", 2)
