"""
Shared application rate limiter (slowapi).

Registered on the FastAPI app in app.main (app.state.limiter + exception
handler). Individual routes opt in with the @limiter.limit(...) decorator and
must accept a `request: Request` parameter (slowapi locates it by type).

NOTE: the default in-memory backend is per-process. On a multi-instance /
autoscale deployment each instance keeps its own counters, so effective limits
are looser than configured. For strict global limits, point slowapi at a shared
store (e.g. Redis) via storage_uri — see slowapi docs. Per-process limiting
still meaningfully blunts brute-force and cost-abuse from a single client.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
