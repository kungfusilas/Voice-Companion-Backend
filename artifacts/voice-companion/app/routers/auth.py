"""
Auth router — proxies to Supabase Auth API and validates JWTs.

Endpoints:
  POST /api/auth/signup   — create account with email + password
  POST /api/auth/login    — sign in with email + password → access_token + refresh_token
  POST /api/auth/refresh  — exchange refresh_token for new access_token
  POST /api/auth/oauth    — verify a Supabase OAuth JWT (from Google / Apple, client-side)
  GET  /api/auth/me       — decode JWT, return user info (no DB call)
"""
import os
import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from app.auth_middleware import verify_token

router = APIRouter()


def _supabase_url() -> str:
    url = os.environ.get("SUPABASE_URL", "")
    if not url:
        raise HTTPException(500, "SUPABASE_URL not configured")
    return url.rstrip("/")


def _service_key() -> str:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not key:
        raise HTTPException(500, "SUPABASE_SERVICE_KEY not configured")
    return key


def _auth_headers() -> dict:
    return {
        "apikey": _service_key(),
        "Authorization": f"Bearer {_service_key()}",
        "Content-Type": "application/json",
    }


# ── Request / response models ─────────────────────────────────────────────────

class SignupRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str

class OAuthVerifyRequest(BaseModel):
    access_token: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/signup")
async def signup(req: SignupRequest):
    """
    Create a new user via Supabase Admin API.
    If email confirmation is disabled in your Supabase project,
    the response will include a full session (access_token + refresh_token).
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{_supabase_url()}/auth/v1/admin/users",
            headers=_auth_headers(),
            json={
                "email": req.email,
                "password": req.password,
                "email_confirm": True,  # auto-confirm for apps without email flow
            },
        )
    if resp.status_code not in (200, 201):
        body = resp.json()
        raise HTTPException(
            status_code=resp.status_code,
            detail=body.get("msg") or body.get("message") or "Signup failed",
        )
    user = resp.json()
    return {"user_id": user.get("id"), "email": user.get("email")}


@router.post("/login")
async def login(req: LoginRequest):
    """
    Sign in with email + password.
    Returns access_token, refresh_token, expires_in, and basic user info.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{_supabase_url()}/auth/v1/token?grant_type=password",
            headers=_auth_headers(),
            json={"email": req.email, "password": req.password},
        )
    if resp.status_code != 200:
        body = resp.json()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=body.get("error_description") or body.get("msg") or "Login failed",
        )
    data = resp.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_in": data.get("expires_in", 3600),
        "token_type": "bearer",
        "user": {
            "id": data["user"]["id"],
            "email": data["user"]["email"],
        },
    }


@router.post("/refresh")
async def refresh(req: RefreshRequest):
    """
    Exchange a refresh_token for a new access_token.
    """
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            f"{_supabase_url()}/auth/v1/token?grant_type=refresh_token",
            headers=_auth_headers(),
            json={"refresh_token": req.refresh_token},
        )
    if resp.status_code != 200:
        body = resp.json()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=body.get("error_description") or body.get("msg") or "Refresh failed",
        )
    data = resp.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", req.refresh_token),
        "expires_in": data.get("expires_in", 3600),
        "token_type": "bearer",
    }


@router.post("/oauth")
async def oauth_verify(req: OAuthVerifyRequest):
    """
    Verify a Supabase OAuth access_token (issued after Google / Apple sign-in
    handled client-side by @supabase/supabase-js). Validates the JWT signature
    via the JWKS endpoint and returns the user's id and email.
    """
    from app.auth_middleware import _get_public_keys
    import jwt as _jwt

    keys = _get_public_keys()
    if not keys:
        raise HTTPException(500, "No public keys available for token verification")

    try:
        header = _jwt.get_unverified_header(req.access_token)
    except Exception:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    kid = header.get("kid")
    alg = header.get("alg", "ES256")
    candidates = [k for k_id, k in keys if k_id == kid] or [k for _, k in keys]

    for public_key in candidates:
        try:
            payload = _jwt.decode(
                req.access_token,
                public_key,
                algorithms=[alg],
                audience="authenticated",
            )
            return {
                "user_id": payload.get("sub"),
                "email": payload.get("email"),
                "role": payload.get("role"),
            }
        except _jwt.ExpiredSignatureError:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
        except Exception:
            continue

    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")


@router.get("/me")
async def me(user_id: str = Depends(verify_token)):
    """
    Return the current user's id, decoded from the Bearer token.
    No database call — pure JWT inspection.
    """
    return {"user_id": user_id}
