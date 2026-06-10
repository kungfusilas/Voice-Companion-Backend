"""
Photo upload endpoint — Premium+ only.
Stores user-sent photos in Supabase Storage (private bucket "user-photos")
and returns a signed URL that is valid for 24 hours (for display + Claude vision).

POST /api/photo/upload
  multipart file field: "file"
  Returns: { "storage_path": "...", "display_url": "..." }
"""
import os
import uuid
import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from app.auth_middleware import verify_token
from app.routers.tier_check import fetch_tier, is_premium_or_higher

router = APIRouter()

_BUCKET = "user-photos"
_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
_SIGNED_URL_TTL_SECS = 86400        # 24 hours
_ALLOWED_MIME: set[str] = {
    "image/jpeg", "image/jpg", "image/png",
    "image/webp", "image/gif", "image/heic",
}


def _supa_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _supa_headers() -> dict[str, str]:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {"apikey": key, "Authorization": f"Bearer {key}"}


async def _ensure_bucket() -> None:
    """Idempotently create the private user-photos bucket."""
    url = _supa_url()
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                f"{url}/storage/v1/bucket",
                headers={**_supa_headers(), "Content-Type": "application/json"},
                json={
                    "id": _BUCKET,
                    "name": _BUCKET,
                    "public": False,
                    "file_size_limit": _MAX_FILE_SIZE,
                    "allowed_mime_types": list(_ALLOWED_MIME),
                },
            )
    except Exception:
        pass  # 409 conflict = already exists — silently skip


@router.post("/upload")
async def upload_photo(
    file: UploadFile = File(...),
    user_id: str = Depends(verify_token),
):
    """
    Upload a user photo to Supabase Storage.  Premium+ gate enforced server-side.
    Returns a 24-hour signed URL for display and Claude vision input.
    """
    tier = await fetch_tier(user_id)
    if not is_premium_or_higher(tier):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "plan_required",
                "required": "premium",
                "message": "Sending photos requires a Premium plan or higher.",
            },
        )

    ct = (file.content_type or "application/octet-stream").split(";")[0].strip().lower()
    if ct not in _ALLOWED_MIME and not ct.startswith("image/"):
        raise HTTPException(status_code=400, detail="Only image files are accepted")

    image_bytes = await file.read()
    if len(image_bytes) > _MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Image too large — maximum 10 MB")
    if len(image_bytes) < 50:
        raise HTTPException(status_code=400, detail="Image file appears empty")

    ext_map = {
        "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png",
        "image/webp": "webp", "image/gif": "gif", "image/heic": "heic",
    }
    ext = ext_map.get(ct, "jpg")
    storage_path = f"{user_id}/{uuid.uuid4().hex}.{ext}"

    supa_url = _supa_url()
    if not supa_url:
        raise HTTPException(status_code=503, detail="Storage not configured")

    await _ensure_bucket()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            up = await client.post(
                f"{supa_url}/storage/v1/object/{_BUCKET}/{storage_path}",
                headers={**_supa_headers(), "Content-Type": ct},
                content=image_bytes,
            )
        if up.status_code not in (200, 201):
            raise HTTPException(
                status_code=502,
                detail=f"Storage upload failed ({up.status_code}): {up.text[:200]}",
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Storage error: {exc}")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            sign = await client.post(
                f"{supa_url}/storage/v1/object/sign/{_BUCKET}/{storage_path}",
                headers={**_supa_headers(), "Content-Type": "application/json"},
                json={"expiresIn": _SIGNED_URL_TTL_SECS},
            )
        if sign.status_code != 200:
            raise HTTPException(status_code=502, detail="Could not generate signed URL")
        sign_data = sign.json()
        signed_path: str = sign_data.get("signedURL") or sign_data.get("signedUrl") or ""
        display_url = f"{supa_url}{signed_path}" if signed_path.startswith("/") else signed_path
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Signing error: {exc}")

    return {"storage_path": storage_path, "display_url": display_url}
