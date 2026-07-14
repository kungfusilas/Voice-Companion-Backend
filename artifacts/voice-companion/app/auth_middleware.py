"""
JWT auth middleware for Supabase-issued tokens.

Supabase signs JWTs with ECC (P-256 / ES256) keys.  We verify tokens by
fetching the project's public JWKS endpoint and caching the keys in memry.
No shared secret is required.

Usage in a route:
    from app.auth_middleware import verify_token

    @router.post("/...")
    async def my_route(user_id: str = Depends(verify_token)):
        ...
"""
import asyncio
import os
import time

import httpx
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

_security = HTTPBearer(auto_error=False)

_JWKS_CACHE: dict = {"entries": [], "fetched_at": 0.0}
_CACHE_TTL = 3600.0  # re-fetch keys at most once per hour
_ALLOWED_ALGS = ["ES256", "RS256"]
_jwks_lock = asyncio.Lock()


def _jwks_url() -> str:
    """Derive the JWKS URL from the SUPABASE_URL environment variable."""
    base = (os.environ.get("SUPABASE_URL") or os.environ.get("VITE_SUPABASE_URL", "")).rstrip("/")
    if not base:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SUPABASE_URL is not configured",
        )
    return f"{base}/auth/v1/.well-known/jwks.json"


async def _get_public_keys() -> list[tuple[str | None, object]]:
    """
    Return cached list of (kid, public_key) tuples.
    Refreshes from the JWKS endpoint when the cache is stale or empty.
    Uses an asyncio lock to prevent thundering-herd fetches at startup.
    """
    now = time.monotonic()
    if _JWKS_CACHE["entries"] and now - _JWKS_CACHE["fetched_at"] < _CACHE_TTL:
        return _JWKS_CACHE["entries"]

    async with _jwks_lock:
        # Re-check inside the lock — another coroutine may have populated it.
        now = time.monotonic()
        if _JWKS_CACHE["entries"] and now - _JWKS_CACHE["fetched_at"] < _CACHE_TTL:
            return _JWKS_CACHE["entries"]

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(_jwks_url())
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
            _JWKS_CACHE["fetched_at"] = time.monotonic()

        return _JWKS_CACHE["entries"]


async def verify_token(
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
    # SECURITY: never trust the alg in the unverified token header.
    alg = header.get("alg", "ES256")
    if alg not in _ALLOWED_ALGS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    keys = await _get_public_keys()
    if not keys:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No public keys available for token verification",
        )

    candidates = [k for k_id, k in keys if k_id == kid] or [k for _, k in keys]

    for public_key in candidates:
        try:
            payload = jwt.decode(
                token,
                public_key,
                algorithms=_ALLOWED_ALGS,
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
        except Exception:
            continue

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid token",
        headers={"WWW-Authenticate": "Bearer"},
    )


