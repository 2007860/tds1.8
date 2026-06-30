import base64
import time
import uuid
from collections import defaultdict, deque
from typing import Any, Dict, Optional

from fastapi import Body, FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

TOTAL_ORDERS = 44
RATE_LIMIT = 16
WINDOW = 10.0

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Fixed catalog
CATALOG = [{"id": i} for i in range(1, TOTAL_ORDERS + 1)]

# Idempotency storage
idempotency_store: Dict[str, Dict[str, Any]] = {}

# Per-client buckets
client_buckets = defaultdict(deque)


def encode_cursor(index: int) -> str:
    return base64.urlsafe_b64encode(str(index).encode()).decode()


def decode_cursor(cursor: Optional[str]) -> int:
    if not cursor:
        return 0
    try:
        return int(base64.urlsafe_b64decode(cursor.encode()).decode())
    except Exception:
        return 0


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    client = request.headers.get("X-Client-Id", "anonymous")
    now = time.monotonic()

    bucket = client_buckets[client]

    while bucket and (now - bucket[0]) >= WINDOW:
        bucket.popleft()

    if len(bucket) >= RATE_LIMIT:
        retry_after = max(1, int(WINDOW - (now - bucket[0])))

        return JSONResponse(
            status_code=429,
            headers={
                "Retry-After": str(retry_after)
            },
            content={
                "detail": "Rate limit exceeded"
            },
        )

    bucket.append(now)

    return await call_next(request)


@app.get("/")
def root():
    return {"status": "ok"}


@app.post("/orders", status_code=201)
def create_order(
    body: Dict[str, Any] = Body(default_factory=dict),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    if idempotency_key in idempotency_store:
        return JSONResponse(
            status_code=200,
            content=idempotency_store[idempotency_key],
        )

    order = {
        "id": str(uuid.uuid4()),
        **body,
    }

    idempotency_store[idempotency_key] = order

    return order


@app.get("/orders")
def list_orders(
    limit: int = Query(10, ge=1),
    cursor: Optional[str] = None,
):
    start = decode_cursor(cursor)

    if start < 0:
        start = 0

    if start > TOTAL_ORDERS:
        start = TOTAL_ORDERS

    end = min(start + limit, TOTAL_ORDERS)

    items = CATALOG[start:end]

    next_cursor = None
    if end < TOTAL_ORDERS:
        next_cursor = encode_cursor(end)

    return {
        "items": items,
        "next_cursor": next_cursor,
    }