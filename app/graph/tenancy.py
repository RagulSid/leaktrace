"""One FalkorDB graph per tenant, named lt_<tenant>.

The tenant always comes from server-side context (auth token, CLI flag, process env),
never from model output. The id is validated so it can never smuggle anything into a key.
"""

import re

_TENANT_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
GRAPH_PREFIX = "lt_"


class InvalidTenant(ValueError):
    pass


def graph_name(tenant: str) -> str:
    if not isinstance(tenant, str) or not _TENANT_RE.fullmatch(tenant):
        raise InvalidTenant(f"invalid tenant id: {tenant!r}")
    return GRAPH_PREFIX + tenant
