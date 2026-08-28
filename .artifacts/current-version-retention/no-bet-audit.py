"""Summarize current deterministic decisions without mutating application data."""

import json
from collections import Counter

from sqlalchemy import text

from app.main import repository


with repository.engine.connect() as connection:
    rows = connection.execute(
        text("SELECT payload FROM predictions ORDER BY created_at DESC")
    ).mappings().all()

items = []
reason_counts = Counter()
status_counts = Counter()
for row in rows:
    prediction = json.loads(row["payload"])
    decision = prediction.get("decision") or {}
    fixture = repository.fixture(prediction.get("fixture_id"))
    reason_codes = decision.get("reason_codes") or []
    reason_counts.update(reason_codes)
    status_counts[decision.get("status") or "missing"] += 1
    items.append(
        {
            "fixture_id": prediction.get("fixture_id"),
            "home": ((fixture or {}).get("home_team") or {}).get("name"),
            "away": ((fixture or {}).get("away_team") or {}).get("name"),
            "model": prediction.get("model_key"),
            "ai": (prediction.get("ai") or {}).get("status"),
            "decision": decision.get("status"),
            "reasons": reason_codes,
            "edge": decision.get("expected_edge"),
            "confidence": decision.get("model_confidence"),
            "odds_status": (prediction.get("market_assessment") or {}).get("odds_status"),
            "phase": prediction.get("phase"),
            "completeness": prediction.get("data_completeness"),
        }
    )

print(
    json.dumps(
        {
            "total": len(items),
            "statuses": dict(status_counts),
            "reasons": dict(reason_counts),
            "items": items,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
)
