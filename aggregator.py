"""Temporal aggregation: turn FRAMES_PER_CYCLE frame results into one verdict."""

from collections import Counter

import config


def aggregate(results):
    """Majority-vote a cycle. Returns {key, status, message, confidence}."""
    if not results:
        return {"key": "IDLE", "status": "NO_DETECTION",
                "message": "No frames captured.", "confidence": 0.0}

    quality_fails = sum(r["status"] == "QUALITY_ERROR" for r in results)
    if quality_fails >= config.QUALITY_FAIL_LIMIT:
        reasons = [r["reason"] for r in results if r["status"] == "QUALITY_ERROR"]
        top = Counter(reasons).most_common(1)[0][0]
        hint = {
            "too dark": "Scene is too dark.",
            "too bright": "Too much glare.",
            "blurry": "Hold the phone steady.",
        }.get(top, "Image quality is low.")
        return {"key": "QUALITY", "status": "QUALITY_ERROR",
                "message": f"Image quality low. {hint}", "confidence": 0.0}

    hits = [r for r in results if r["status"] == "SUCCESS"]
    if not hits:
        if any(r["status"] == "OCR_ERROR" for r in results):
            return {"key": "OCR", "status": "OCR_ERROR",
                    "message": "Bus detected, but the sign is unreadable.",
                    "confidence": 0.0}
        return {"key": "NONE", "status": "NO_DETECTION",
                "message": "No bus detected.", "confidence": 0.0}

    # Vote on route and destination independently so a partial read still counts.
    routes = Counter(r["bus_number"] for r in hits if r["bus_number"])
    dests = Counter(r["destination"] for r in hits if r["destination"])

    route = routes.most_common(1)[0][0] if routes else None
    dest = dests.most_common(1)[0][0] if dests else None
    confidence = round(sum(r["confidence"] for r in hits) / len(hits), 2)

    if route and dest:
        message = f"Route {route} to {dest}."
    elif route:
        message = f"Route {route}. Destination unclear."
    else:
        message = f"Bus to {dest}. Route number unclear."

    return {"key": f"{route}|{dest}", "status": "SUCCESS",
            "message": message, "confidence": confidence}


def should_announce(verdict, last_key):
    """Suppress a repeat announcement of the identical verdict."""
    return verdict["key"] != last_key
