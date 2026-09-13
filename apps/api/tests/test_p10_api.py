"""P10 HTTP contract tests for the model registry API."""

import os
import sys

if "app.main" not in sys.modules:
    os.environ.setdefault("DATABASE_URL", "sqlite:///test_football_ai_p10.db")
    os.environ.setdefault("USE_DEMO_DATA", "false")
    os.environ.setdefault("API_DEEPSEEK_KEY", "")
    os.environ.setdefault("API_CHATGPT_KEY", "")

from fastapi.testclient import TestClient

from app.main import app, model_registry_service
from app.model_registry import ModelRecord, artifact_hash


client = TestClient(app)

_ADMIN = {"x-admin-key": "dev-admin-key"}


def _registered_record(model_version: str, status: str = "draft") -> ModelRecord:
    record = ModelRecord(
        model_key="poisson",
        model_version=model_version,
        artifact_hash=artifact_hash({"model": "poisson", "version": model_version}),
        status=status,
        feature_version="p3-v1",
    )
    return model_registry_service.register(record)


def test_models_endpoint_exposes_families_and_records() -> None:
    response = client.get("/api/models")

    assert response.status_code == 200
    payload = response.json()
    family_keys = {item["model_key"] for item in payload["families"]}
    assert {"baseline", "elo", "poisson", "dixon_coles", "deepseek", "chatgpt", "ensemble", "calibrated_ensemble"} <= family_keys
    assert isinstance(payload["records"], list)
    assert "record_count" in payload


def test_model_status_transition_requires_admin() -> None:
    assert client.post("/api/admin/models/poisson/v1/status", json={"status": "candidate"}).status_code == 401


def test_model_status_transition_validates_lifecycle() -> None:
    _registered_record("p10-v1")

    # Draft must be evaluated (candidate) before production.
    draft_block = client.post(
        "/api/admin/models/poisson/p10-v1/status",
        headers=_ADMIN,
        json={"status": "champion"},
    )
    assert draft_block.status_code == 400

    candidate = client.post(
        "/api/admin/models/poisson/p10-v1/status",
        headers=_ADMIN,
        json={"status": "candidate"},
    )
    assert candidate.status_code == 200
    assert candidate.json()["updated"]["status"] == "candidate"

    unevaluated = client.post(
        "/api/admin/models/poisson/p10-v1/status",
        headers=_ADMIN,
        json={"status": "champion"},
    )
    assert unevaluated.status_code == 400

    promoted = client.post(
        "/api/admin/models/poisson/p10-v1/status",
        headers=_ADMIN,
        json={"status": "champion", "promotion_evidence": {"promoted": True}},
    )
    assert promoted.status_code == 200
    assert promoted.json()["updated"]["status"] == "champion"

    # The public endpoint now reflects the champion record.
    models = client.get("/api/models").json()
    assert models["champions"]["poisson"]["model_version"] == "p10-v1"


def test_model_status_transition_rejects_unknown_model() -> None:
    response = client.post(
        "/api/admin/models/ghost/v1/status",
        headers=_ADMIN,
        json={"status": "retired"},
    )

    assert response.status_code == 400
