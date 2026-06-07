"""
JWT auth middleware for Supabase-issued tokens.

Supabase now signs JWTs with ECC (P-256 / ES256) keys.  We verify tokens by
fetching the project's public JWKS endpoint and caching the keys in memory.
No shared secret is required.

Usage in a route:
    from app.auth_middleware import verify_token

    @router.post("/...")
    async def my_route(user_id: str = Depends(verify_token)):
        ...
"""
import time
import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

_security = HTTPBearer(auto_error=False)

# Supabase JWKS endpoint for this project
JWKS_URL = (
    "https://kyeqlkqbhwaiwwnvjrtt.supabase.co/auth/v1/.well-known/jwks.json"
)

_JWKS_CACHE: dict = {"entries": [], "fetched_at": 0.0}
_CACHE_TTL = 3600.0  # re-fetch keys at most once per hour


def _get_public_keys() -> list[tuple[str | None, object]]:
    """
    Return cached list of (kid, public_key) tuples.
    Refreshes from the JWKS endpoint when the cache is stale or empty.
    """
    now = time.monotonic()
    if _JWKS_CACHE["entries"] and now - _JWKS_CACHE["fetched_at"] < _CACHE_TTL:
        return _JWKS_CACHE["entries"]

    try:
        resp = httpx.get(JWKS_URL, timeout=10.0)
        resp.raise_for_status()
    except Exception as exc:
        if _JWKS_CACHE["entries"]:
            return _JWKS_CACHE["entries"]
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not fetch auth public keys: {exc}",
        )

    entries: list[tuple[str | None, object]] = []
    for jwk in resp.json().get("keys", []):
        kty = jwk.get("kty", "")
        kid = jwk.get("kid")
        try:
            if kty == "EC":
                key = jwt.algorithms.ECAlgorithm.from_jwk(jwk)
            elif kty == "RSA":
                key = jwt.algorithms.RSAAlgorithm.from_jwk(jwk)
            else:
                continue
            entries.append((kid, key))
        except Exception:
            continue

    if entries:
        _JWKS_CACHE["entries"] = entries
        _JWKS_CACHE["fetched_at"] = now

    return _JWKS_CACHE["entries"]


def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> str:
    """
    FastAPI dependency.  Validates a Supabase JWT in the Authorization header
    and returns the user's UUID (the 'sub' claim).

    Raises HTTP 401 if the token is missing, expired, or has an invalid
    signature.  Keys are fetched from Supabase's JWKS endpoint and cached.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    try:
        header = jwt.get_unverified_header(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    kid = header.get("kid")
    alg = header.get("alg", "ES256")

    keys = _get_public_keys()
    if not keys:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No public keys available for token verification",
        )

    # Prefer the key matching the token's kid; fall back to trying all keys.
    candidates = [k for k_id, k in keys if k_id == kid] or [k for _, k in keys]

    last_exc: Exception | None = None
    for public_key in candidates:
        try:
            payload = jwt.decode(
                token,
                public_key,
                algorithms=[alg],
                audience="authenticated",
            )
            user_id: str | None = payload.get("sub")
            if not user_id:
                raise ValueError("No sub claim in token")
            return user_id
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except Exception as exc:
            last_exc = exc
            continue

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid token",
        headers={"WWW-Authenticate": "Bearer"},
    )
