"""Graph schema: the allowlists of labels and relationship types, and index creation."""

from redis.exceptions import ResponseError

from app.graph import queries
from app.graph.client import TenantGraph

# Every node label the product writes (BUILD_PROMPT §7). Templated statements accept only these.
NODE_LABELS = frozenset({
    "Entity",
    # network and operations
    "Source", "Sink", "Junction", "Segment", "Valve", "Pump", "Tank", "Consumer", "Zone", "Meter", "Sensor",
    "Workload", "PDU", "Report", "Reading", "Incident", "Hypothesis", "Option", "Decision", "Approval",
    "Action", "WorkOrder", "Verification", "Advisory", "Execution", "AuditEvent",
    # authority, memory, coordination
    "AuthorityPolicy", "Episode", "Fact", "Playbook", "Conversation", "Message", "Agent", "Task", "User",
    # company knowledge
    "Person", "Team", "Vendor", "Document", "Chunk", "Ticket", "Policy", "SOP", "Review", "IncidentReport",
    "PracticeData",
})

REL_TYPES = frozenset({
    "FLOWS_TO", "MEASURES", "MONITORS", "IN_ZONE", "ROUTED_THROUGH", "LOCATED_IN", "ADJACENT_TO",
    "SERVES", "POWERED_BY", "RUNS_ON", "DEPENDS_ON",
    "ABOUT", "PART_OF", "INVOLVED", "HAS_OPTION", "DECIDED", "CHOSE", "APPROVES", "IMPLEMENTS", "VERIFIES",
    "ROLLED_BACK", "AUTHORIZED_BY",
    "OF", "EVIDENCED_BY", "SUPERSEDES", "DERIVED_FROM", "IN", "WITH",
    "FOR", "CLAIMED_BY", "HANDED_OFF_TO", "BLOCKED_BY",
    "OWNS", "MAINTAINS", "MEMBER_OF", "EXPERT_IN", "PERFORMED", "MENTIONS", "DESCRIBES", "EXTRACTED_FROM",
    "JUSTIFIED_BY", "ON", "OPERATES", "AUTHORED",
})

# Labels looked up by id. All of them get a range index on `id`.
INDEXED_LABELS = sorted(NODE_LABELS)


def check_label(label: str) -> str:
    if label not in NODE_LABELS:
        raise ValueError(f"label not in schema: {label!r}")
    return label


def check_rel(rel: str) -> str:
    if rel not in REL_TYPES:
        raise ValueError(f"relationship type not in schema: {rel!r}")
    return rel


def ensure_schema(tg: TenantGraph) -> int:
    """Create the id indexes. Safe to run again: existing indexes are skipped. Returns how many were created."""
    created = 0
    template = queries.load("schema_node_index")
    statements = [(f"schema_node_index:{lb}", template.replace("{label}", check_label(lb))) for lb in INDEXED_LABELS]
    statements.append(("schema_flow_edge_index", queries.load("schema_flow_edge_index")))
    for name, text in statements:
        try:
            tg.write_text(name, text)
            created += 1
        except ResponseError as e:
            if "already indexed" not in str(e):
                raise
    return created
