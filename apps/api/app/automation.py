"""Database-backed recurring jobs for sync, prediction, and settlement."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable

from .evidence_chain import evidence_needs_enrichment, localize_evidence_players, merge_evidence, should_use_secondary


class AutomationRunner:
    """Run due domain jobs while preserving durable run history across restarts."""

    def __init__(
        self,
        settings: Any,
        repository: Any,
        schedule_sync: Any,
        league_sync: Any,
        evidence_provider: Any,
        prediction_service: Any,
        bankroll_service: Any,
        settlement_service: Any,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.schedule_sync = schedule_sync
        self.league_sync = league_sync
        self.evidence_provider = evidence_provider
        self.prediction_service = prediction_service
        self.bankroll_service = bankroll_service
        self.settlement_service = settlement_service
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._jobs: dict[str, tuple[int, Callable[[], Awaitable[dict[str, Any]]]]] = {
            "fixtures": (settings.automation_fixture_interval_minutes, self._sync_fixtures),
            "standings": (settings.automation_standings_interval_minutes, self._sync_standings),
            "analysis": (settings.automation_analysis_interval_minutes, self._analyze_upcoming),
            "settlement": (settings.automation_settlement_interval_minutes, self._settle_finished),
        }

    async def run_loop(self) -> None:
        """Run immediately on startup, then wake on the configured short tick."""

        self._stop.clear()
        while not self._stop.is_set():
            try:
                await self.run_due()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Per-job execution already records bounded failures; keep the loop alive.
                pass
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=max(10, int(self.settings.automation_tick_seconds)),
                )
            except TimeoutError:
                continue

    def stop(self) -> None:
        self._stop.set()

    async def run_due(self) -> list[dict[str, Any]]:
        """Run each due job once without overlapping inside this process."""

        if self._lock.locked():
            return []
        async with self._lock:
            runs = []
            for job_name, (interval_minutes, _) in self._jobs.items():
                if self._is_due(job_name, interval_minutes):
                    runs.append(await self._execute_job(job_name))
            return runs

    async def run_job(self, job_name: str) -> dict[str, Any]:
        """Force one job while sharing the normal non-overlap lock."""

        async with self._lock:
            return await self._execute_job(job_name)

    async def _execute_job(self, job_name: str) -> dict[str, Any]:
        """Run one known job now and persist its complete lifecycle."""

        item = self._jobs.get(job_name)
        if item is None:
            raise ValueError(f"Unknown automation job: {job_name}")
        started_at = datetime.now(UTC).isoformat()
        run = self.repository.start_job_run(job_name, started_at)
        try:
            result = await item[1]()
            errors = result.get("errors") or []
            status = "partial" if errors else "success"
            item_count = int(result.get("item_count", 0))
            error_summary = "; ".join(str(error) for error in errors[:5])[:500] or None
        except Exception as error:
            result = None
            status = "failed"
            item_count = 0
            error_summary = _bounded_error(error)
        finished_at = datetime.now(UTC).isoformat()
        return self.repository.finish_job_run(
            run["id"],
            finished_at,
            status,
            item_count,
            result,
            error_summary,
        )

    def _is_due(self, job_name: str, interval_minutes: int) -> bool:
        last = self.repository.last_job_run(job_name)
        if not last:
            return True
        value = last.get("finished_at") or last.get("started_at")
        try:
            timestamp = datetime.fromisoformat(value).astimezone(UTC)
        except (TypeError, ValueError):
            return True
        minutes = (
            self.settings.automation_failure_backoff_minutes
            if last.get("status") in {"failed", "partial", "running"}
            else interval_minutes
        )
        return datetime.now(UTC) - timestamp >= timedelta(minutes=max(1, minutes))

    async def _sync_fixtures(self) -> dict[str, Any]:
        result = await self.schedule_sync.force_refresh()
        return {**result, "item_count": int(result.get("item_count", 0))}

    async def _sync_standings(self) -> dict[str, Any]:
        result = await self.league_sync.force_refresh()
        return {**result, "item_count": int(result.get("item_count", 0))}

    async def _analyze_upcoming(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        counts = {
            "candidate_count": 0,
            "evidence_count": 0,
            "evidence_refresh_count": 0,
            "public_evidence_count": 0,
            "prediction_count": 0,
            "bet_count": 0,
        }
        errors: list[str] = []
        refresh_attempts = 0
        for fixture in self.repository.list_fixtures():
            kickoff = _as_utc(fixture.get("kickoff"))
            if (
                fixture.get("status") != "scheduled"
                or kickoff is None
                or kickoff < now
                or kickoff - now > timedelta(hours=self.settings.prediction_lead_hours)
            ):
                continue
            counts["candidate_count"] += 1
            try:
                if (
                    refresh_attempts < self.settings.automation_evidence_refresh_limit
                    and self._evidence_refresh_due(fixture, kickoff, now)
                ):
                    refresh_attempts += 1
                    try:
                        fixture = await self._refresh_evidence(fixture)
                        counts["evidence_refresh_count"] += 1
                    except Exception as error:
                        errors.append(f"{fixture.get('id')}: {_bounded_error(error)}")
                        if not fixture.get("evidence"):
                            fixture = await self._refresh_public_evidence(fixture)
                            counts["public_evidence_count"] += 1
                elif not fixture.get("evidence"):
                    fixture = await self._refresh_public_evidence(fixture)
                    counts["public_evidence_count"] += 1
                if fixture.get("evidence_synced_at"):
                    counts["evidence_count"] += 1
                context = fixture.get("evidence")
                if not context or not context.get("synced_at"):
                    continue
                localize_evidence_players(context)
                model_keys = list(getattr(self.prediction_service, "model_keys", ()))
                if not model_keys:
                    latest = self.repository.latest(fixture["id"])
                    due_model_keys: list[str] | None = None if self._should_predict(latest, context, now) else []
                else:
                    competition_id = getattr(self.prediction_service, "competition_id", None)
                    due_model_keys = [
                        key for key in model_keys
                        if self._should_predict(
                            self.repository.latest(fixture["id"], key, competition_id),
                            context,
                            now,
                        )
                    ]
                if due_model_keys == []:
                    continue
                created = await self.prediction_service.create(fixture, context, due_model_keys) if model_keys else await self.prediction_service.create(fixture, context)
                predictions = created if isinstance(created, list) else [created]
                counts["prediction_count"] += len(predictions)
                for prediction in predictions:
                    bet = self.bankroll_service.place_for_prediction(prediction, fixture, context)
                    if bet:
                        counts["bet_count"] += 1
            except Exception as error:
                errors.append(f"{fixture.get('id')}: {_bounded_error(error)}")
        return {**counts, "item_count": counts["prediction_count"], "errors": errors[:20]}

    def _evidence_refresh_due(
        self,
        fixture: dict[str, Any],
        kickoff: datetime,
        now: datetime,
    ) -> bool:
        if not self.evidence_provider.configured:
            return False
        context = fixture.get("evidence") or {}
        synced_at = _as_utc(context.get("synced_at"))
        stale = (
            synced_at is None
            or context.get("source") == "thesportsdb-partial"
            or now - synced_at >= timedelta(minutes=self.settings.evidence_refresh_minutes)
        )
        near_lineup = (
            kickoff - now <= timedelta(hours=self.settings.lineup_refresh_hours)
            and not (context.get("lineup") or {}).get("confirmed")
        )
        return stale or near_lineup or evidence_needs_enrichment(context)

    async def _refresh_evidence(self, fixture: dict[str, Any]) -> dict[str, Any]:
        existing = fixture.get("evidence") or {}
        fetch_secondary = getattr(self.evidence_provider, "fetch_secondary", None)
        fetcher = fetch_secondary if should_use_secondary(existing) and callable(fetch_secondary) else self.evidence_provider.fetch
        context = merge_evidence(existing, await fetcher(fixture))
        return self.repository.save_fixture_evidence(fixture["id"], context) or fixture

    async def _refresh_public_evidence(self, fixture: dict[str, Any]) -> dict[str, Any]:
        fetch_public = getattr(self.evidence_provider, "fetch_public", None)
        if not callable(fetch_public):
            return fixture
        context = await fetch_public(fixture)
        return self.repository.save_fixture_evidence(fixture["id"], context) or fixture

    def _should_predict(
        self,
        latest: dict[str, Any] | None,
        context: dict[str, Any],
        now: datetime,
    ) -> bool:
        if latest is None:
            return True
        lineup_confirmed = bool((context.get("lineup") or {}).get("confirmed"))
        if lineup_confirmed and latest.get("phase") != "confirmed_lineup":
            return True
        ai_status = (latest.get("ai") or {}).get("status")
        if not ai_status:
            return True
        if ai_status not in {"failed", "unconfigured"}:
            return False
        created_at = _as_utc(latest.get("created_at"))
        return created_at is None or now - created_at >= timedelta(minutes=self.settings.model_retry_minutes)

    async def _settle_finished(self) -> dict[str, Any]:
        result = self.settlement_service.settle_finished()
        return {**result, "item_count": int(result.get("prediction_count", 0))}


def _as_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (TypeError, ValueError):
        return None


def _bounded_error(error: Exception) -> str:
    return (str(error).replace("\n", " ").replace("\r", " ")[:300] or error.__class__.__name__)
