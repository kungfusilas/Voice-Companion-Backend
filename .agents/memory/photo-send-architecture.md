---
name: Photo send feature architecture
description: How user-sent photos flow through BondAI — upload → storage → vision chat
---

## Architecture

1. **Upload** (`POST /api/photo/upload`): Frontend sends multipart image → backend stores in Supabase Storage private bucket `user-photos` at `{user_id}/{uuid}.{ext}` → returns 24h signed URL.
2. **Chat with vision** (`POST /api/chat/stream` with `image_url`): Backend downloads the signed URL via HTTP, passes bytes as base64 to `claude.stream_message_with_image` (no tool-use loop for vision messages). Consumes **2 quota units** (first from regular `check_message_quota`, second from the photo block).
3. **Premium gate**: Enforced server-side in both the upload endpoint (`fetch_tier` → `is_premium_or_higher`) and the stream endpoint (`_TIER_RANK` check).
4. **Memory extraction**: Runs normally from companion reply — reply text describes photo contents, so facts land in memories organically.
5. **UI**: Camera button → dropdown with "Ask for a selfie" + "Send a photo". User-sent images render as right-aligned bubbles; companion selfies remain left-aligned.

**Why base64 instead of URL-fetch-at-Claude-time:**
Supabase signed URLs expire after 24h. Downloading in the upload handler while bytes are in memory avoids a second round-trip and guarantees bytes are available even if the signed URL format changes.

**How to apply:**
Any future vision-related feature should reuse `claude.stream_message_with_image` and the photo upload endpoint pattern.
