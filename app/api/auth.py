"""Login and signed tokens. The tenant a request works on comes only from a verified token.

Users live in their tenant's graph as User nodes (PBKDF2-SHA256 password hash). A token is
base64url(JSON claims) + "." + base64url(HMAC-SHA256(claims, LEAKTRACE_SECRET)). Claims: sub, role,
tenant, exp. No endpoint accepts a tenant from the request body or query string.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.exceptions import ResponseError

from app import config
from app.graph.client import TenantGraph, rows
from app.graph.tenancy import InvalidTenant

ROLES = ("staff", "operator", "tech", "manager", "authority", "integration")
PBKDF2_ITERATIONS = 120_000

_bearer = HTTPBearer(auto_error=False)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return digest.hex(), salt


def add_user(tg: TenantGraph, user: str, role: str, password: str, name: str | None = None) -> None:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    pw_hash, salt = hash_password(password)
    tg.write("user_upsert", {"id": user, "role": role, "name": name or user, "pw_hash": pw_hash,
                             "pw_salt": salt, "source": "synthetic"})


def issue_token(user: str, role: str, tenant: str, ttl_s: int | None = None) -> tuple[str, float]:
    exp = time.time() + (config.TOKEN_TTL_S if ttl_s is None else ttl_s)
    claims = _b64(json.dumps({"sub": user, "role": role, "tenant": tenant, "exp": exp}, sort_keys=True).encode())
    sig = _b64(hmac.new(config.SECRET.encode(), claims.encode(), hashlib.sha256).digest())
    return f"{claims}.{sig}", exp


def login(tenant: str, user: str, password: str) -> dict | None:
    try:
        tg = TenantGraph(tenant)
        found = rows(tg.read("user_get", {"id": user}))
    except (InvalidTenant, ResponseError):
        return None  # unknown tenant looks the same as a wrong password
    if not found:
        hash_password(password)  # same work either way
        return None
    u = found[0]
    if not hmac.compare_digest(hash_password(password, u["pw_salt"])[0], u["pw_hash"]):
        return None
    token, exp = issue_token(u["id"], u["role"], tenant)
    return {"token": token, "role": u["role"], "tenant": tenant, "expires_at": exp}


@dataclass(frozen=True)
class Principal:
    user: str
    role: str
    tenant: str

    def graph(self) -> TenantGraph:
        return TenantGraph(self.tenant)


def verify(token: str) -> Principal:
    try:
        claims_b64, sig_b64 = token.split(".")
        expected = hmac.new(config.SECRET.encode(), claims_b64.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(sig_b64)):
            raise ValueError("bad signature")
        c = json.loads(_unb64(claims_b64))
        if c["exp"] < time.time():
            raise ValueError("expired")
        if c["role"] not in ROLES:
            raise ValueError("bad role")
        return Principal(c["sub"], c["role"], c["tenant"])
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")


def current(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Principal:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "login required")
    return verify(creds.credentials)


def require(*roles: str):
    def dep(p: Principal = Depends(current)) -> Principal:
        if p.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"role {p.role} may not do this")
        return p

    return dep
