from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Optional
import uuid
import time
import base64

app = FastAPI(title="Orders API")

# -----------------------------
# CORS
# -----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================================
# CONFIG
# ==========================================================

TOTAL_ORDERS = 52          # Assigned value
RATE_LIMIT = 16            # Requests
WINDOW = 10                # Seconds

# ==========================================================
# IN-MEMORY STORAGE
# ==========================================================

# Stores orders created through POST /orders
created_orders = {}

# Stores Idempotency-Key -> order
idempotency_store = {}

# Stores client rate limits
# {
#   "client1": [timestamps]
# }
rate_limits = {}

# ==========================================================
# FIXED CATALOG FOR PAGINATION
# IDs 1 ... 52
# ==========================================================

catalog = [
    {
        "id": i,
        "item": f"Item {i}",
        "price": i * 10
    }
    for i in range(1, TOTAL_ORDERS + 1)
]

# ==========================================================
# CURSOR HELPERS
# ==========================================================

def encode_cursor(index: int) -> str:
    return base64.b64encode(str(index).encode()).decode()


def decode_cursor(cursor: Optional[str]) -> int:
    if not cursor:
        return 0

    try:
        return int(base64.b64decode(cursor).decode())
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor")


# ==========================================================
# RATE LIMIT
# ==========================================================

def check_rate_limit(client_id: str):
    now = time.time()

    timestamps = rate_limits.get(client_id, [])

    # Keep only timestamps inside the last 10 seconds
    timestamps = [t for t in timestamps if now - t < WINDOW]

    if len(timestamps) >= RATE_LIMIT:
        retry_after = max(1, int(WINDOW - (now - timestamps[0])))

        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={
                "Retry-After": str(retry_after)
            }
        )

    timestamps.append(now)

    rate_limits[client_id] = timestamps


# ==========================================================
# POST /orders
# Idempotent order creation
# ==========================================================

@app.post("/orders", status_code=201)
def create_order(
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    client_id: Optional[str] = Header("anonymous", alias="X-Client-Id"),
):
    check_rate_limit(client_id)

    # Same key -> same response
    if idempotency_key and idempotency_key in idempotency_store:
        return idempotency_store[idempotency_key]

    order = {
        "id": str(uuid.uuid4()),
        "status": "created"
    }

    created_orders[order["id"]] = order

    if idempotency_key:
        idempotency_store[idempotency_key] = order

    return JSONResponse(status_code=201, content=order)


# ==========================================================
# GET /orders
# Cursor Pagination
# ==========================================================

@app.get("/orders")
def list_orders(
    limit: int = 10,
    cursor: Optional[str] = None,
    client_id: Optional[str] = Header("anonymous", alias="X-Client-Id"),
):
    check_rate_limit(client_id)

    if limit <= 0:
        raise HTTPException(status_code=400, detail="limit must be > 0")

    start = decode_cursor(cursor)

    end = start + limit

    items = catalog[start:end]

    if end >= len(catalog):
        next_cursor = None
    else:
        next_cursor = encode_cursor(end)

    return {
        "items": items,
        "next_cursor": next_cursor
    }


# ==========================================================
# OPTIONAL HEALTH CHECK
# ==========================================================

@app.get("/")
def root():
    return {
        "message": "Orders API Running",
        "total_catalog_orders": TOTAL_ORDERS,
        "rate_limit": f"{RATE_LIMIT} requests / {WINDOW} seconds"
    }

