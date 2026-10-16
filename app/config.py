"""Settings read from the environment (and a local .env file if present)."""

import os
import secrets

from dotenv import load_dotenv

load_dotenv()

FALKORDB_HOST = os.getenv("FALKORDB_HOST", "localhost")
FALKORDB_PORT = int(os.getenv("FALKORDB_PORT", "6380"))
FALKORDB_PASSWORD = os.getenv("FALKORDB_PASSWORD") or None
DEMO_TENANT = os.getenv("LEAKTRACE_DEMO_TENANT", "demo")

# Every read gets a server-side timeout so a bad query cannot hang a request.
READ_TIMEOUT_MS = int(os.getenv("LEAKTRACE_READ_TIMEOUT_MS", "2000"))

# Token signing secret. Without one, a random secret is made per process (tokens die on restart).
SECRET = os.getenv("LEAKTRACE_SECRET") or secrets.token_hex(32)
SECRET_IS_EPHEMERAL = not os.getenv("LEAKTRACE_SECRET")
TOKEN_TTL_S = int(os.getenv("LEAKTRACE_TOKEN_TTL_S", str(12 * 3600)))

# Execution. An approval is valid for at most APPROVAL_TTL_S (an approver may choose a shorter time).
APPROVAL_TTL_S = int(os.getenv("LEAKTRACE_APPROVAL_TTL_S", str(30 * 60)))
# Lease a field worker holds on a valve move; after it runs out the step goes back to open.
DEFAULT_LEASE_S = int(os.getenv("LEAKTRACE_LEASE_S", "60"))
MAX_LEASE_S = 600
# A step whose lease ran out this many times is abandoned and the execution fails.
MOVE_MAX_ATTEMPTS = 3
# How long verification waits for fresh readings when the policy sets no verify_window_s.
VERIFY_WINDOW_S = 120
