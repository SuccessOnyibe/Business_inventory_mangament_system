"""Stock requests: extracted workflows; URLs and transactions are unchanged."""

from fastapi import HTTPException
from psycopg.types.json import Jsonb


def begin_stock_request(cursor, request_id, operation, payload, user_id):
    """Reserve a request key, or return the result of an earlier successful request."""
    # The unique key makes a simultaneous retry wait for the first transaction.
    # If that transaction fails, its reservation rolls back and the retry can run.
    cursor.execute(
        """
        INSERT INTO stock_requests (request_id, operation, request_payload, user_id)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (request_id) DO NOTHING
        RETURNING request_id;
        """,
        (request_id, operation, Jsonb(payload), user_id)
    )
    if cursor.fetchone() is not None:
        return None

    cursor.execute(
        "SELECT operation, request_payload, response, user_id FROM stock_requests WHERE request_id = %s;",
        (request_id,)
    )
    previous = cursor.fetchone()
    # A key belongs to one operation and body; changing either is a new request.
    # Another user (or a legacy key with no owner) cannot retrieve this response.
    if previous[3] != user_id or previous[0] != operation or previous[1] != payload:
        raise HTTPException(status_code=409, detail="Idempotency key was already used for another request")
    if previous[2] is None:
        raise HTTPException(status_code=409, detail="Stock request has no saved response")
    return previous[2]


def finish_stock_request(cursor, request_id, response):
    # Save the original result in the SAME transaction as stock and movements.
    # Replays return this result, even if the inventory changes again later.
    cursor.execute(
        "UPDATE stock_requests SET response = %s WHERE request_id = %s;",
        (Jsonb(response), request_id)
    )
