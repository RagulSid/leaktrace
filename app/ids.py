"""Server-generated identifiers. Nothing here ever comes from user or model text."""

import secrets

_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I/L: easy to read out on a phone


def _hex(n: int = 3) -> str:
    return secrets.token_hex(n)


def incident_id() -> str:
    return "INC-" + _hex().upper()


def incident_key(incident: str) -> str:
    """Lowercase key for plan ids, which also name the what-if capacity property (^[a-z0-9_]+$)."""
    return incident.split("-", 1)[1].lower() + _hex(2)


def report_id() -> str:
    return "REP-" + _hex(4).upper()


def report_code() -> str:
    return "R-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


def decision_id() -> str:
    return "DEC-" + _hex(4).upper()


def task_id() -> str:
    return "TSK-" + _hex(4).upper()


def episode_id() -> str:
    return "EP-" + _hex(6).upper()


def reading_id() -> str:
    return "RD-" + _hex(6).upper()


def audit_id() -> str:
    return "AUD-" + _hex(6).upper()


def approval_id() -> str:
    return "APR-" + _hex(4).upper()


def execution_id() -> str:
    return "EXE-" + _hex(4).upper()


def action_id() -> str:
    return "ACT-" + _hex(5).upper()


def verification_id() -> str:
    return "VER-" + _hex(4).upper()


def fact_id() -> str:
    return "F-" + _hex(4).upper()
