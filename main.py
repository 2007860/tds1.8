import base64
import time
import uuid
from collections import defaultdict
from typing import Any

from fastapi import Body, FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

TOTAL_ORDERS = 44
RATE_LIMIT = 16
WINDOW = 10

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Fixed catalog
catalog = [{"id": i} for i in range(1, TOTAL_ORDERS + 1)]

# Idempotency storage
idempotency = {}

# Per-client rate limit buckets
buckets = defaultdict(list)


def encode_cursor(index: int) -> str:
    return base64.urlsafe_b64encode(str(index).encode()).decode()


def decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        return int(base64.urlsafe_b64decode(cursor.encode()).decode())
    except Exception:
        return 0


@app.middleware("http")
async def limiter(request: Request, call_next):
    client = request.headers.get("X-Client-Id", "anonymous")
    now = time.time()

    bucket = [t for t in buckets[client] if now - t < WINDOW]
    buckets[client] = bucket

    if len(bucket) >= RATE_LIMIT:
        retry = max(1, int(WINDOW - (now - bucket[0])))

        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded"},
            headers={"Retry-After": str(retry)},
        )

    bucket.append(now)

    return await call_next(request)


@app.post("/orders", status_code=201)
def create_order(
    body: dict[str, Any] = Body(default={}),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    if idempotency_key in idempotency:
        return JSONResponse(
            status_code=200,
            content=idempotency[idempotency_key],
        )

    order = {
        "id": str(uuid.uuid4()),
        **body,
    }

    idempotency[idempotency_key] = order

    return order


@app.get("/orders")
def list_orders(
    limit: int = Query(10, ge=1),
    cursor: str | None = None,
):
    start = decode_cursor(cursor)

    items = catalog[start : start + limit]

    next_cursor = None
    if start + len(items) < TOTAL_ORDERS:
        next_cursor = encode_cursor(start + len(items))

    return {
        "items": items,
        "next_cursor": next_cursor,
    }


@app.get("/")
def root():
    return {"status": "ok"}