
import time
import uuid
import base64
from collections import defaultdict
from fastapi import FastAPI, Header, HTTPException, Query
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

orders = [{"id": i} for i in range(1, TOTAL_ORDERS + 1)]
idempotency_store = {}
rate_buckets = defaultdict(list)

def encode_cursor(idx: int):
    return base64.urlsafe_b64encode(str(idx).encode()).decode()

def decode_cursor(cur: str):
    try:
        return int(base64.urlsafe_b64decode(cur.encode()).decode())
    except Exception:
        return 0

@app.middleware("http")
async def rate_limit(request, call_next):
    client = request.headers.get("X-Client-Id", "anonymous")
    now = time.time()

    bucket = [t for t in rate_buckets[client] if now - t < WINDOW]
    rate_buckets[client] = bucket

    if len(bucket) >= RATE_LIMIT:
        retry = max(1, int(WINDOW - (now - bucket[0])))
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(retry)},
            content={"detail": "Rate limit exceeded"},
        )

    bucket.append(now)
    response = await call_next(request)
    return response

@app.post("/orders", status_code=201)
def create_order(idempotency_key: str = Header(..., alias="Idempotency-Key")):
    if idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]

    order = {"id": str(uuid.uuid4())}
    idempotency_store[idempotency_key] = order
    return order

@app.get("/orders")
def list_orders(limit: int = Query(10, ge=1), cursor: str | None = None):
    start = decode_cursor(cursor) if cursor else 0
    items = orders[start:start + limit]
    next_cursor = None
    if start + limit < len(orders):
        next_cursor = encode_cursor(start + limit)

    return {
        "items": items,
        "next_cursor": next_cursor,
    }

@app.get("/")
def root():
    return {"status": "ok"}
