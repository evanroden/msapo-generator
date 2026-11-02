"""Structural dispatch for shared saved row receipts, never current authority."""
import json


def decoded(text):
    message = "The saved row review is damaged or exceeds its budget. Original report and source evidence remain unchanged."
    if not isinstance(text, str) or len(text) > 4_000_000:
        raise ValueError(message)
    try:
        value = json.loads(text)
        if not isinstance(value, dict):
            raise ValueError(message)
        kind = value.get("kind")
        if kind in ("workorders", "maintenance"):
            from app.monthly_report_work_order_review_flow import decoded as decode
        elif kind == "training":
            from app.monthly_report_training_review_flow import decoded as decode
        else:
            raise ValueError(message)
        return decode(text)
    except (ValueError, KeyError, TypeError, AttributeError, IndexError,
            OverflowError, RecursionError) as exc:
        raise ValueError(message) from exc
