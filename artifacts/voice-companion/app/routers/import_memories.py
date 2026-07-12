import os
import json
import anthropic
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

_CATEGORIES = ["family", "work", "location", "health", "goals", "personality", "history"]

class ImportRequest(BaseModel):
    text: str
    user_id: str

@router.post("/api/import-memories")
async def import_memories(body: ImportRequest):
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="No text provided")
    if not body.user_id:
        raise HTTPException(status_code=400, detail="user_id required")

    ai = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    cats = ", ".join(_CATEGORIES)
    prompt = (
        f"Extract key personal facts from this text. "
        f"Categorize each into one of: {cats}.\n"
        'Output only JSON lines, one per fact: {"category": "...", "fact": "..."}\n'
        "Facts must be specific, 1-2 sentences max. Extract 5 to 20 facts. No other text.\n\n"
        f"Text:\n{body.text[:8000]}"
    )
    msg_resp = await ai.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = msg_resp.content[0].text.strip()

    facts = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if obj.get("category") in _CATEGORIES and obj.get("fact"):
                facts.append({"user_id": body.user_id, "category": obj["category"], "fact": obj["fact"]})
        except json.JSONDecodeError:
            continue

    if not facts:
        raise HTTPException(status_code=422, detail="Could not extract any facts from the text")

    sb_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    sb_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    headers = {
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    async with httpx.AsyncClient(timeout=10.0) as hx:
        r = await hx.post(f"{sb_url}/rest/v1/user_core_facts", headers=headers, json=facts)
    if r.status_code not in (200, 201):
        raise HTTPException(status_code=500, detail=f"Storage error: {r.text}")

    categories = sorted({f["category"] for f in facts})
    return {"imported": len(facts), "categories": categories}
