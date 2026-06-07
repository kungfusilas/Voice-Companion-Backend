"""
JWT auth middleware for Supabase-issued tokens.

Usage in a route:
    from app.auth_middleware import verify_token

    @router.post("/...")
    async def my_route(user_id: str = Depends(verify_token)):
        ...
"""
import os
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

_security = HTTPBearer(auto_error=False)


def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(_security),
) -> str:
    """
    FastAPI dependency.  Validates the Supabase JWT in the Authorization header
    and returns the user's UUID (the 'sub' claim).

    Raises HTTP 401 if the token is missing, expired, or has an invalid
    signature.  Uses SUPABASE_JWT_SECRET from the environment (HS256).
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    jwt_secret = os.environ.get("SUPABASE_JWT_SECRET", "")
    if not jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server auth not configured (SUPABASE_JWT_SECRET missing)",
        )

    try:
        payload = jwt.decode(
            credentials.credentials,
            jwt_secret,
            algorithms=["HS256"],
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
