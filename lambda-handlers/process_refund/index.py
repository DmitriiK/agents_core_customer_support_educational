import json
import threading
import time
import uuid

# One warm Lambda container keeps this map. A cold start starts empty.
_RESULTS = {}
_LOCK = threading.Lock()

MAX_ATTEMPTS = 3
BASE_DELAY_SECONDS = 0.05


class RetryableFailure(Exception):
    """Temporary failure. The same idempotency key may be retried."""


def _issue_refund(order_id, amount, reason, idempotency_key):
    return {
        "status": "approved",
        "order_id": order_id,
        "refund_amount": amount,
        "reason": reason,
        "idempotency_key": idempotency_key,
        "refund_id": str(uuid.uuid4()),
        "message": (
            f"Refund of ${amount} for order {order_id} processed successfully"
        ),
    }


def call_with_backoff(
    operation,
    max_attempts=MAX_ATTEMPTS,
    base_delay=BASE_DELAY_SECONDS,
    sleep=time.sleep,
):
    """Retry RetryableFailure with delays of base, 2*base, 4*base, ..."""
    delay = base_delay
    for attempt in range(max_attempts):
        try:
            return operation()
        except RetryableFailure:
            if attempt == max_attempts - 1:
                raise
            sleep(delay)
            delay *= 2


def refund_customer(
    order_id,
    amount,
    reason,
    idempotency_key,
    issuer=None,
    sleep=time.sleep,
):
    """Issue one refund for this idempotency key.

    A retry with the same key returns the stored result and does not create
    another refund. Example key: "operation-123".
    """
    if issuer is None:
        issuer = _issue_refund

    if idempotency_key:
        with _LOCK:
            existing = _RESULTS.get(idempotency_key)
        if existing is not None:
            return dict(existing)

    result = call_with_backoff(
        lambda: issuer(order_id, amount, reason, idempotency_key),
        sleep=sleep,
    )

    if not idempotency_key:
        return result

    with _LOCK:
        existing = _RESULTS.get(idempotency_key)
        if existing is not None:
            return dict(existing)
        _RESULTS[idempotency_key] = result
        return dict(result)


def clear_results():
    with _LOCK:
        _RESULTS.clear()


def handler(event, context):
    amount = event.get("amount", 0)
    order_id = event.get("order_id", "unknown")
    reason = event.get("reason", "not specified")
    idempotency_key = event.get("idempotency_key")

    try:
        result = refund_customer(order_id, amount, reason, idempotency_key)
    except RetryableFailure:
        return {
            "statusCode": 503,
            "body": json.dumps(
                {
                    "status": "unavailable",
                    "order_id": order_id,
                    "idempotency_key": idempotency_key,
                    "message": "Refund could not be completed after retries",
                }
            ),
        }

    return {"statusCode": 200, "body": json.dumps(result)}
