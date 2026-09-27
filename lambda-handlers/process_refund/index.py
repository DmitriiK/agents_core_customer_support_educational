import json


def handler(event, context):
    amount = event.get("amount", 0)
    order_id = event.get("order_id", "unknown")
    reason = event.get("reason", "not specified")

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "status": "approved",
                "order_id": order_id,
                "refund_amount": amount,
                "reason": reason,
                "message": (
                    f"Refund of ${amount} for order {order_id} processed successfully"
                ),
            }
        ),
    }
