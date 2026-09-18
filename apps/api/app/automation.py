"""Database-backed recurring jobs for sync, prediction, and settlement."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable

from .data import CHINA_TZ, unavailable_context
from .evidence_chain import (
    evidence_needs_daily_refresh,
    evidence_needs_enrichment,
    localize_evidence_players,
    merge_evidence,
)
from .prompt_contract import DEFAULT_PROMPT_CONTRACT
from .schedule_sync import deduplicate_fixtures
from .notifier import notify_due_fixtures

# 首发未确认时的重试节流：通常开球前 20-40 分钟才公布，固定窗口会错过。
LINEUP_RETRY_MINUTES = 10


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
        historical_accumulation_service: Any | None = None,
        dongqiudi_sync_service: Any | None = None,
        historical_data_service: Any | None = None,
        model_registry_service: Any | None = None,
        football_data_service: Any | None = None,
        clubeelo_service: Any | None = None,
        dongqiudi_team_service: Any | None = None,
        squad_fallback_provider: Any | None = None,
    ) -> None:
        self.settings = settings
        self.repository = repository
        self.schedule_sync = schedule_sync
        self.league_sync = league_sync
        self.evidence_provider = evidence_provider
        self.prediction_service = prediction_service
        self.bankroll_service = bankroll_service
        self.settlement_service = settlement_service
        self.historical_accumulation_service = historical_accumulation_service
        self.dongqiudi_sync_service = dongqiudi_sync_service
        self.historical_data_service = historical_data_service
        self.model_registry_service = model_registry_service
        self.football_data_service = football_data_service
        self.clubeelo_service = clubeelo_service
        self.dongqiudi_team_service = dongqiudi_team_service
        self.squad_fallback_provider = squad_fallback_provider
        self._lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self._jobs: dict[str, tuple[int, Callable[[], Awaitable[dict[str, Any]]]]] = {
            "fixtures": (max(1, int(getattr(settings, "automation_fixture_interval_minutes", 1440))), self._sync_fixtures),
            "evidence": (max(1, int(getattr(settings, "automation_evidence_interval_minutes", 1440))), self._refresh_daily_evidence),
            "lineup": (max(1, int(getattr(settings, "automation_lineup_interval_minutes", 5))), self._refresh_lineups),
            "standings": (settings.automation_standings_interval_minutes, self._sync_standings),
            "analysis": (settings.automation_analysis_interval_minutes, self._analyze_upcoming),
            "settlement": (settings.automation_settlement_interval_minutes, self._settle_finished),
        }
        if historical_accumulation_service is not None:
            self._jobs["historical_accumulation"] = (
                max(1, int(getattr(settings, "automation_historical_accumulation_interval_minutes", 1440))),
                self._accumulate_historical,
            )
        if historical_data_service is not None:
            self._jobs["historical_backfill"] = (
                max(10, int(getattr(settings, "automation_historical_backfill_interval_minutes", 60))),
                self._backfill_historical_season,
            )
        if model_registry_service is not None:
            self._jobs["ensemble_learning"] = (
                max(60, int(getattr(settings, "automation_ensemble_learning_interval_minutes", 10080))),
                self._learn_ensemble_weights,
            )
            self._jobs["fd_confirmatory_research"] = (
                max(60, int(getattr(settings, "automation_fd_confirmatory_research_interval_minutes", 20160))),
                self._run_fd_confirmatory_research,
            )
        if football_data_service is not None:
            self._jobs["fd_backfill"] = (
                max(60, int(getattr(settings, "automation_fd_backfill_interval_minutes", 360))),
                self._sync_football_data,
            )
        if clubeelo_service is not None and bool(getattr(settings, "clubeelo_enabled", True)):
            self._jobs["clubeelo"] = (
                max(60, int(getattr(settings, "automation_clubeelo_interval_minutes", 1440))),
                self._sync_clubeelo,
            )
        if dongqiudi_team_service is not None and bool(getattr(settings, "dongqiudi_enabled", True)):
            self._jobs["squad_backfill"] = (
                max(30, int(getattr(settings, "automation_squad_backfill_interval_minutes", 60))),
                self._backfill_squads,
            )
        if dongqiudi_sync_service is not None and bool(getattr(settings, "dongqiudi_enabled", True)):
            self._jobs["dongqiudi_schedule"] = (
                max(60, int(getattr(settings, "automation_dongqiudi_schedule_interval_minutes", 60))),
                self._sync_dongqiudi_schedule,
            )
            self._jobs["dongqiudi_scores"] = (
                max(1, int(getattr(settings, "automation_dongqiudi_score_interval_minutes", 5))),
                self._sync_dongqiudi_scores,
            )
            self._jobs["dongqiudi_prematch"] = (
                max(1, int(getattr(settings, "automation_dongqiudi_prematch_interval_minutes", 5))),
                self._sync_dongqiudi_prematch,
            )
            if bool(getattr(settings, "notify_webhook_url", "")) or bool(getattr(settings, "notify_email_to", "")):
                self._jobs["prediction_notify"] = (
                    max(1, int(getattr(settings, "automation_notify_interval_minutes", 5))),
                    self._notify_predictions,
                )

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
                if job_name == "analysis" and not getattr(self.settings, "automation_analysis_enabled", True):
                    continue
                if self._is_due(job_name, interval_minutes):
                    runs.append(await self._execute_job(job_name))
            return runs

    async def run_job(self, job_name: str, *, force: bool = False) -> dict[str, Any]:
        """Force one job while sharing the normal non-overlap lock."""

        async with self._lock:
            callback = (lambda: self._analyze_upcoming(force=True)) if force and job_name == "analysis" else None
            return await self._execute_job(job_name, callback=callback)

    async def _execute_job(
        self,
        job_name: str,
        *,
        callback: Callable[[], Awaitable[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        """Run one known job now and persist its complete lifecycle."""

        item = self._jobs.get(job_name)
        if item is None:
            raise ValueError(f"Unknown automation job: {job_name}")
        started_at = datetime.now(UTC).isoformat()
        run = self.repository.start_job_run(job_name, started_at)
        try:
            result = await (callback or item[1])()
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
        if last.get("status") in {"failed", "partial", "running"}:
            return datetime.now(UTC) - timestamp >= timedelta(
                minutes=max(1, int(self.settings.automation_failure_backoff_minutes))
            )
        if job_name in {"fixtures", "evidence"}:
            return timestamp.astimezone(CHINA_TZ).date() < datetime.now(CHINA_TZ).date()
        return datetime.now(UTC) - timestamp >= timedelta(minutes=max(1, interval_minutes))

    async def _sync_fixtures(self) -> dict[str, Any]:
        result = await self.schedule_sync.force_refresh()
        return {**result, "item_count": int(result.get("item_count", 0))}

    async def _refresh_daily_evidence(self) -> dict[str, Any]:
        """Refresh missing or stale pre-match evidence without running models."""

        now = datetime.now(UTC)
        candidates = self._future_scheduled_fixtures(now)
        limit = max(0, int(getattr(self.settings, "automation_evidence_refresh_limit", 32)))
        counts = {"candidate_count": len(candidates), "refresh_count": 0, "skipped_count": 0, "deferred_count": 0}
        errors: list[str] = []
        for fixture in candidates:
            existing = fixture.get("evidence") or {}
            if not evidence_needs_daily_refresh(existing, now, self.settings.evidence_refresh_minutes):
                counts["skipped_count"] += 1
                continue
            if limit and counts["refresh_count"] >= limit:
                counts["deferred_count"] += 1
                continue
            try:
                fetcher = getattr(self.evidence_provider, "fetch_public", None)
                if not callable(fetcher):
                    raise RuntimeError("TheSportsDB 证据源不支持每日刷新")
                context = merge_evidence(existing, await fetcher(fixture))
                localize_evidence_players(context)
                self.repository.save_fixture_evidence(fixture["id"], context)
                counts["refresh_count"] += 1
            except Exception as error:
                errors.append(f"{fixture.get('id')}: {_bounded_error(error)}")
        return {**counts, "item_count": counts["refresh_count"], "errors": errors[:20]}

    async def _refresh_lineups(self) -> dict[str, Any]:
        """Refresh each scheduled fixture at the configured final-hour windows."""

        now = datetime.now(UTC)
        offsets = self._lineup_offsets()
        window_minutes = max(1, int(getattr(self.settings, "automation_lineup_interval_minutes", 5)))
        candidates = self._future_scheduled_fixtures(now)
        counts = {"candidate_count": 0, "synced_count": 0, "confirmed_count": 0, "skipped_count": 0}
        errors: list[str] = []
        fetcher = getattr(self.evidence_provider, "fetch_lineup", None)
        if not candidates:
            return {**counts, "item_count": 0, "errors": []}
        if not callable(fetcher):
            return {**counts, "item_count": 0, "errors": ["证据源不支持只刷新首发"]}
        for fixture in candidates:
            kickoff = _as_utc(fixture.get("kickoff"))
            if kickoff is None:
                continue
            delta_minutes = (kickoff - now).total_seconds() / 60
            context = fixture.get("evidence") or unavailable_context()
            if (context.get("lineup") or {}).get("confirmed"):
                counts["skipped_count"] += 1
                continue
            markers = context.get("automation_refresh") or {}
            # 首发通常开球前 20-40 分钟才公布：进入最大窗口后按
            # LINEUP_RETRY_MINUTES 节流重试，直到确认或开球，而不是每个偏移只抓一次。
            offset = next(
                (
                    value
                    for value in offsets
                    if 0 < delta_minutes <= value + window_minutes
                ),
                None,
            )
            if offset is None:
                continue
            marker_key = f"lineup_{offset}_at"
            last_attempt = _as_utc(markers.get(marker_key))
            if last_attempt is not None and (now - last_attempt).total_seconds() < LINEUP_RETRY_MINUTES * 60:
                continue
            counts["candidate_count"] += 1
            try:
                incoming = await fetcher(fixture)
                merged = merge_evidence(context, incoming)
                localize_evidence_players(merged)
                refresh_state = dict(merged.get("automation_refresh") or {})
                refresh_state[marker_key] = datetime.now(UTC).replace(microsecond=0).isoformat()
                merged["automation_refresh"] = refresh_state
                updated = self.repository.save_fixture_evidence(fixture["id"], merged)
                fixture = updated or fixture
                counts["synced_count"] += 1
                if (merged.get("lineup") or {}).get("confirmed"):
                    counts["confirmed_count"] += 1
            except Exception as error:
                errors.append(f"{fixture.get('id')}: {_bounded_error(error)}")
        return {**counts, "item_count": counts["synced_count"], "errors": errors[:20]}

    def _future_scheduled_fixtures(self, now: datetime) -> list[dict[str, Any]]:
        today = now.astimezone(CHINA_TZ).date()
        last_day = today + timedelta(days=max(1, int(getattr(self.settings, "schedule_lookahead_days", 7))))
        fixtures: list[dict[str, Any]] = []
        for fixture in deduplicate_fixtures(self.repository.list_fixtures()):
            if fixture.get("status") != "scheduled":
                continue
            kickoff = _as_utc(fixture.get("kickoff"))
            if kickoff is None or kickoff < now or kickoff.astimezone(CHINA_TZ).date() > last_day:
                continue
            fixtures.append(fixture)
        return fixtures

    def _lineup_offsets(self) -> list[int]:
        raw = str(getattr(self.settings, "lineup_refresh_offsets_minutes", "60,30"))
        values = {int(item.strip()) for item in raw.split(",") if item.strip().isdigit() and int(item.strip()) > 0}
        return sorted(values or {60, 30}, reverse=True)

    async def _sync_standings(self) -> dict[str, Any]:
        result = await self.league_sync.force_refresh()
        return {**result, "item_count": int(result.get("item_count", 0))}

    async def _sync_football_data(self) -> dict[str, Any]:
        """Ingest the next pending Football-Data.co.uk season (one per run)."""

        from .competition_registry import season_for
        from .football_data_provider import DIVISION_MAP, season_code, season_csv_url, sync_season
        from .team_names import to_chinese_team_name

        divisions = ("epl", "laliga")
        seasons_back = max(1, int(getattr(self.settings, "football_data_seasons_backfill", 5)))
        today = datetime.now(UTC).date()
        for division in divisions:
            current = season_for(division, today)
            for step in range(seasons_back):
                season = current - step
                marker = f"fd:{division}:{season}"
                if self.repository.sync_marker(marker):
                    continue
                csv_text = await self.football_data_service.fetch_season_csv(division, season)
                if csv_text is None:
                    self.repository.save_sync_marker(marker, 0)
                    continue
                result = sync_season(
                    self.repository,
                    csv_text,
                    division,
                    season,
                    chinese_name=to_chinese_team_name,
                )
                self.repository.save_sync_marker(marker, int(result.get("matches") or 0))
                return {**result, "item_count": int(result.get("matches") or 0)}
        return {"status": "complete", "reason": "所有赛季已回填", "item_count": 0}

    async def _sync_clubeelo(self) -> dict[str, Any]:
        from .clubeelo_provider import sync_ratings
        from .team_names import to_chinese_team_name

        csv_text = await self.clubeelo_service.fetch_on()
        return sync_ratings(self.repository, csv_text, localize=to_chinese_team_name)

    async def _backfill_squads(self) -> dict[str, Any]:
        """Fill squad rosters for fixtures whose dongqiudi twin lacks one.

        The roster lives on the team snapshot (one fetch per team, cached);
        matches without a twin row simply have no dongqiudi team id yet.
        """

        limit = max(1, int(getattr(self.settings, "squad_backfill_limit", 12)))
        roster_ttl = timedelta(
            minutes=max(1, int(getattr(self.settings, "team_cache_ttl_minutes", 360)))
        )
        reader = getattr(self.repository, "list_fixtures", None)
        if not callable(reader):
            return {"status": "unavailable", "reason": "repository 不支持 fixtures", "item_count": 0}
        now = datetime.now(UTC)
        fixture_reader = getattr(self.repository, "fixture", None)
        targets: list[tuple[dict[str, Any], str, str]] = []
        for fixture in reader():
            if fixture.get("status") != "scheduled":
                continue
            kickoff = _as_utc(fixture.get("kickoff"))
            if kickoff is None or kickoff < now:
                continue
            # 球队 ID 在懂球帝孪生行（数据域命名空间），canonical 行没有。
            match_id = (fixture.get("external_ids") or {}).get("dongqiudi")
            twin = fixture_reader(f"dongqiudi-{match_id}") if (match_id and callable(fixture_reader)) else None
            if not twin:
                continue
            free_data = fixture.get("free_team_data") or {}
            if _has_fixture_squad(free_data.get("home")) and _has_fixture_squad(free_data.get("away")):
                continue  # 双侧阵容齐的场次直接跳过
            for side in ("home", "away"):
                if _has_fixture_squad(free_data.get(side)):
                    continue
                twin_id = ((twin.get(f"{side}_team") or {}).get("provider_id") or "")
                if twin_id:
                    targets.append((fixture, side, str(twin_id)))
        synced = 0
        enriched = 0
        fetch_attempts = 0
        errors: list[str] = []
        snapshot_by_team: dict[str, dict[str, Any]] = {}
        for fixture, side, team_id in targets:
            league_key = str(fixture.get("league_key") or "unknown")
            cached = (
                snapshot_by_team.get(team_id)
                or (
                    self.repository.team_snapshot(league_key, team_id)
                    if callable(getattr(self.repository, "team_snapshot", None))
                    else None
                )
            )
            if _team_snapshot_needs_roster_refresh(cached, now, roster_ttl):
                if fetch_attempts >= limit:
                    continue
                fetch_attempts += 1
                try:
                    cached = await self.dongqiudi_team_service.team(team_id)
                    cached["league_key"] = league_key
                    snapshot_by_team[team_id] = cached
                    if _snapshot_roster(cached):
                        self.repository.save_team_snapshot(cached)
                        synced += 1
                    else:
                        fallback = await self._fallback_squad(fixture, side, team_id, league_key)
                        if fallback:
                            cached = fallback
                            snapshot_by_team[team_id] = cached
                            self.repository.save_team_snapshot(cached)
                            synced += 1
                        else:
                            errors.append(f"{team_id}: 懂球帝返回空球员名单，备用数据源也未返回名单")
                            continue
                except Exception as error:
                    fallback = await self._fallback_squad(fixture, side, team_id, league_key)
                    if fallback:
                        cached = fallback
                        snapshot_by_team[team_id] = cached
                        self.repository.save_team_snapshot(cached)
                        synced += 1
                    else:
                        errors.append(f"{team_id}: {_bounded_error(error)}")
                        continue
            roster = _snapshot_roster(cached)
            if not roster and self.squad_fallback_provider is not None:
                fallback = await self._fallback_squad(fixture, side, team_id, league_key)
                if fallback:
                    cached = fallback
                    snapshot_by_team[team_id] = cached
                    self.repository.save_team_snapshot(cached)
                    roster = _snapshot_roster(cached)
                    synced += 1
            if not roster:
                continue
            # 写回 fixture：与既有 _sync_teams 相同的 free_team_data 结构。
            updated = self.repository.fixture(fixture["id"])
            if not updated:
                continue
            free_data = dict(updated.get("free_team_data") or {})
            changed = False
            for candidate_side in ("home", "away"):
                if _has_fixture_squad(free_data.get(candidate_side)):
                    continue
                twin_match_id = (updated.get("external_ids") or {}).get("dongqiudi")
                twin = self.repository.fixture(f"dongqiudi-{twin_match_id}") if twin_match_id else None
                twin_team_id = str(((twin or {}).get(f"{candidate_side}_team") or {}).get("provider_id") or "")
                if twin_team_id and twin_team_id == team_id:
                    free_data[candidate_side] = {
                        "profile": cached.get("team") or {},
                        "squad": roster,
                        "source": cached.get("source") or "dongqiudi",
                    }
                    changed = True
            if changed:
                updated["free_team_data"] = free_data
                updated["free_team_data_synced_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
                self.repository.upsert_fixture(updated)
                enriched += 1
        return {
            "status": "completed",
            "synced": synced,
            "enriched": enriched,
            "fetch_attempts": fetch_attempts,
            "item_count": synced,
            "errors": errors[:10],
        }

    async def _fallback_squad(
        self,
        fixture: dict[str, Any],
        side: str,
        team_id: str,
        league_key: str,
    ) -> dict[str, Any] | None:
        """Use the match-level fallback provider when Dongqiudi has no roster."""

        provider = self.squad_fallback_provider
        fetch = getattr(provider, "fetch", None)
        if not callable(fetch):
            return None
        try:
            context = await fetch(fixture)
        except Exception:
            return None
        roster = (context.get("squads") or {}).get(side)
        if not isinstance(roster, list) or not roster:
            return None
        team = (context.get("teams") or {}).get(side) or fixture.get(f"{side}_team") or {}
        season = fixture.get("season") or {}
        season_year = season.get("year") if isinstance(season, dict) else season
        return {
            "league_key": league_key,
            "team_id": team_id,
            "season": {"year": season_year or datetime.now(UTC).year},
            "updated_at": context.get("synced_at") or datetime.now(UTC).replace(microsecond=0).isoformat(),
            "team": team,
            "roster": roster,
            "roster_count": len(roster),
            "source": "espn-evidence-fallback",
        }

    def _historical_season_targets(self) -> list[tuple[str, int, int]]:
        """List (league, season, existing) pairs below the per-season cap."""

        from .competition_registry import season_for

        seasons_per_league = max(1, int(getattr(self.settings, "historical_seasons_per_league", 3)))
        cap = max(1, int(getattr(self.settings, "historical_max_per_league_season", 100)))
        today = datetime.now(UTC).date()
        targets: list[tuple[str, int, int]] = []
        for code in ("csl", "epl", "laliga"):
            current = season_for(code, today)
            for step in range(seasons_per_league):
                season = current - step
                targets.append((code, season, self.historical_data_service.season_existing(code, season)))
        return [(code, season, existing) for code, season, existing in targets if existing < cap]

    async def _backfill_historical_season(self) -> dict[str, Any]:
        """Fill the least-stocked league season (one pair per run; rate-limit friendly)."""

        provider_descriptor = self.historical_data_service.registry.get("api-football")
        if provider_descriptor is None or not provider_descriptor.configured:
            return {"status": "unavailable", "reason": "api-football 未配置", "item_count": 0}
        targets = self._historical_season_targets()
        if not targets:
            return {"status": "complete", "reason": "所有联赛赛季均达到上限", "item_count": 0}
        code, season, existing = min(targets, key=lambda item: item[2])
        cap = max(1, int(getattr(self.settings, "historical_max_per_league_season", 100)))
        result = await self.historical_data_service.sync_league_history("api-football", code, season, limit=cap)
        return {
            "status": result.get("status", "completed"),
            "league": code,
            "season": season,
            "existing_before": existing,
            "snapshots": result.get("historical_snapshots"),
            "fixtures_result": {
                key: result.get(key)
                for key in ("fixtures", "results", "odds")
                if isinstance(result.get(key), dict)
            },
            "coverage": result.get("coverage"),
            "item_count": int((result.get("fixtures") or {}).get("records_inserted") or 0),
        }

    async def _learn_ensemble_weights(self) -> dict[str, Any]:
        """Learn ensemble weights via the P10 protocol and register the artifact.

        Sample gates apply: below the P6 policy threshold the artifact is
        registered as draft (never promoted), and no metrics are invented.
        """

        from .model_platform import run_model_protocol
        from .model_registry import ModelRecord, artifact_hash, dataset_fingerprint
        from .prediction_intelligence import build_backtest_rows

        settlements = self.repository.fixture_settlements(
            competition_id=getattr(self.settings, "simulation_competition_id", None)
        )
        rows = build_backtest_rows(settlements)
        rows = [
            dict(row, models=dict(row.get("base_predictions") or {}))
            for row in rows
            if row.get("base_predictions") and row.get("actual_outcome") in {"home", "draw", "away"}
        ]
        model_keys = tuple(sorted({key for row in rows for key in row["models"]}))
        if not rows or "poisson" not in model_keys or not any(key != "poisson" for key in model_keys):
            return {
                "status": "insufficient_sample",
                "reason": "缺少 Poisson 与至少一个 LLM 的配对样本",
                "item_count": 0,
            }
        protocol = run_model_protocol(rows, model_keys)
        weights = protocol.get("weights") or {}
        fingerprint = protocol.get("dataset_fingerprint") or dataset_fingerprint(rows)
        version = f"ensemble-learned-{hashlib.sha256(json.dumps(weights, sort_keys=True).encode()).hexdigest()[:12]}"
        metrics = protocol.get("metrics") or {}
        test_samples = int((metrics.get("ensemble") or {}).get("samples") or 0)
        improvement = ((protocol.get("improvement") or {}).get("naive_baseline") or {}).get("brier_improvement")
        promoted = (
            protocol.get("status") == "ok"
            and test_samples >= 30
            and improvement is not None
            and improvement > 0
        )
        record = ModelRecord(
            model_key="ensemble",
            model_version=version,
            artifact_hash=artifact_hash({"weights": weights, "dataset": fingerprint}),
            # 本次运行即评估记录：注册为 candidate，凭门禁证据晋升。
            status="candidate",
            competition_scope="all",
            feature_version=protocol.get("feature_version"),
            dataset_fingerprint=fingerprint,
            training_cutoff=max((str(row.get("prediction_created_at") or "") for row in rows), default=None),
            calibration_version=protocol.get("calibration_version"),
            payload={
                "weights": weights,
                "metrics": metrics,
                "splits": protocol.get("splits"),
                "improvement": protocol.get("improvement"),
                "temperature": protocol.get("temperature"),
                "sample_status": "adequate" if promoted else "low_confidence",
            },
        )
        self.model_registry_service.register(record)
        if promoted:
            self.model_registry_service.transition(
                "ensemble",
                version,
                "champion",
                promotion_evidence={"promoted": True},
            )
        return {
            "status": "promoted" if promoted else "registered_draft",
            "version": version,
            "weights": weights,
            "test_samples": test_samples,
            "improvement": improvement,
            "item_count": 1,
        }

    async def _run_fd_confirmatory_research(self) -> dict[str, Any]:
        """Archive the pre-registered FD LLM-vs-Poisson report after 30 pairs."""

        from .research_engine import filter_settlement_rows_by_source, run_research, validate_hypothesis
        from .prediction_intelligence import build_backtest_rows

        settlements = self.repository.fixture_settlements(
            competition_id=getattr(self.settings, "simulation_competition_id", None)
        )
        filtered = filter_settlement_rows_by_source(
            settlements,
            source="football-data",
            fixture_reader=getattr(self.repository, "fixture", None),
        )
        sample_size = len(build_backtest_rows(filtered))
        if sample_size < 30:
            return {
                "status": "insufficient_sample",
                "source": "football-data",
                "sample_size": sample_size,
                "required_samples": 30,
                "item_count": 0,
            }
        hypothesis = validate_hypothesis(
            statement="Football-Data 历史样本中，LLM 1X2 预测与 Poisson 基线进行预注册配对比较",
            kind="confirmatory",
            selection_rule="按预测创建时间排序，固定使用结算前冻结概率；仅报告配对 Brier、Log Loss，以及存在完整执行链时的 ROI/CLV，不自动晋升模型。",
        )
        run = run_research(
            filtered,
            hypothesis=hypothesis,
            mode="model_comparison",
            job_id="fd-confirmatory-llm-vs-poisson",
            created_by="automation",
            competition_scope="football-data",
            repository=self.repository,
        )
        return {
            "status": run.get("status"),
            "run_id": run.get("run_id"),
            "source": "football-data",
            "sample_size": sample_size,
            "required_samples": 30,
            "item_count": 1 if run.get("run_id") else 0,
        }

    async def _notify_predictions(self) -> dict[str, Any]:
        """Push the AI prediction summary one hour before kickoff."""

        webhook_url = str(getattr(self.settings, "notify_webhook_url", "") or "")
        email_to = str(getattr(self.settings, "notify_email_to", "") or "")
        if not webhook_url and not email_to:
            return {"sent": 0, "skipped": 0}
        email_config = None
        if email_to:
            email_config = {
                "host": str(getattr(self.settings, "notify_smtp_host", "") or "smtp.qq.com"),
                "port": int(getattr(self.settings, "notify_smtp_port", 465) or 465),
                "user": str(getattr(self.settings, "notify_smtp_user", "") or ""),
                "pass": str(getattr(self.settings, "notify_smtp_pass", "") or ""),
                "to": email_to,
            }

        def latest_prediction(fixture: dict[str, Any]) -> dict[str, Any] | None:
            return self.repository.latest_current(
                fixture["id"],
                DEFAULT_PROMPT_CONTRACT.version,
                "chatgpt",
                getattr(self.prediction_service, "competition_id", None),
            )

        def save_evidence(fixture_id: str, context: dict[str, Any]) -> None:
            self.repository.save_fixture_evidence(fixture_id, context)

        return await notify_due_fixtures(
            webhook_url,
            deduplicate_fixtures(self.repository.list_fixtures()),
            latest_prediction,
            save_evidence,
            email_config,
        )

    async def _sync_dongqiudi_schedule(self) -> dict[str, Any]:
        result = await self.dongqiudi_sync_service.sync_schedule()
        return {**result, "item_count": int(result.get("item_count", 0))}

    async def _sync_dongqiudi_scores(self) -> dict[str, Any]:
        result = await self.dongqiudi_sync_service.sync_scores()
        return {**result, "item_count": int(result.get("item_count", 0))}

    async def _sync_dongqiudi_prematch(self) -> dict[str, Any]:
        return await self.dongqiudi_sync_service.sync_prematch_due()

    async def _accumulate_historical(self) -> dict[str, Any]:
        result = await self.historical_accumulation_service.run()
        return {
            **result,
            "item_count": int(result.get("newly_generated_predictions", 0)),
        }

    async def _analyze_upcoming(self, force: bool = False) -> dict[str, Any]:
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
        for fixture in deduplicate_fixtures(self.repository.list_fixtures()):
            kickoff = _as_utc(fixture.get("kickoff"))
            if fixture.get("status") != "scheduled" or kickoff is None or kickoff < now:
                continue
            prediction_window = self._prediction_window(kickoff, now)
            if prediction_window is None:
                continue
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
                refresh_state = context.get("automation_refresh") or {}
                prediction_window = (
                    self._prediction_window(kickoff, now)
                    if force
                    else self._prediction_window(kickoff, now, refresh_state, model_keys)
                )
                current_predictions: dict[str, dict[str, Any] | None] = {}
                lineup_reprediction = False
                odds_reprediction = False
                if prediction_window is None and not force:
                    competition_id = getattr(self.prediction_service, "competition_id", None)
                    if model_keys:
                        current_predictions = {
                            key: self.repository.latest_current(
                                fixture["id"],
                                DEFAULT_PROMPT_CONTRACT.version,
                                key,
                                competition_id,
                            )
                            for key in model_keys
                        }
                    else:
                        current_predictions = {
                            "default": self.repository.latest_current(
                                fixture["id"],
                                DEFAULT_PROMPT_CONTRACT.version,
                            )
                        }
                    if (context.get("lineup") or {}).get("confirmed"):
                        lineup_reprediction = any(
                            self._should_predict(item, context, now, reason="lineup")
                            for item in current_predictions.values()
                        )
                    odds_reprediction = any(
                        self._should_predict(item, context, now, reason="odds")
                        for item in current_predictions.values()
                        if item is not None
                    )
                    if lineup_reprediction or odds_reprediction:
                        prediction_window = 0.0
                if prediction_window is None:
                    continue
                counts["candidate_count"] += 1
                marker_prefix = (
                    "prediction_lineup"
                    if lineup_reprediction
                    else "prediction_odds"
                    if odds_reprediction
                    else f"prediction_{self._prediction_window_token(prediction_window)}"
                )
                if not current_predictions:
                    if not model_keys:
                        latest = self.repository.latest_current(
                            fixture["id"],
                            DEFAULT_PROMPT_CONTRACT.version,
                        )
                        current_predictions = {"default": latest}
                        due_model_keys: list[str] = [] if refresh_state.get(f"{marker_prefix}_default_at") else ["default"]
                    else:
                        competition_id = getattr(self.prediction_service, "competition_id", None)
                        current_predictions = {
                            key: self.repository.latest_current(
                                fixture["id"],
                                DEFAULT_PROMPT_CONTRACT.version,
                                key,
                                competition_id,
                            )
                            for key in model_keys
                        }
                        due_model_keys = [
                            key for key in model_keys
                            if not refresh_state.get(f"{marker_prefix}_{key}_at")
                        ]
                elif lineup_reprediction or odds_reprediction:
                    event_reason = "lineup" if lineup_reprediction else "odds"
                    due_model_keys = [
                        key for key in (model_keys or ["default"])
                        if self._should_predict(current_predictions.get(key), context, now, reason=event_reason)
                    ]
                else:
                    due_model_keys = []
                if due_model_keys == [] and not force:
                    current = [item for item in current_predictions.values() if item]
                    counts["bet_count"] += len(self._place_predictions(current, fixture, context))
                    continue
                created = await self.prediction_service.create(fixture, context, due_model_keys) if model_keys else await self.prediction_service.create(fixture, context)
                predictions = created if isinstance(created, list) else [created]
                counts["prediction_count"] += len(predictions)
                refresh_state = dict(context.get("automation_refresh") or {})
                marked_at = datetime.now(UTC).replace(microsecond=0).isoformat()
                for prediction in predictions:
                    model_key = str(prediction.get("model_key") or (prediction.get("ai") or {}).get("provider") or "default")
                    refresh_state[f"{marker_prefix}_{model_key}_at"] = marked_at
                context["automation_refresh"] = refresh_state
                fixture = self.repository.save_fixture_evidence(fixture["id"], context) or fixture
                counts["bet_count"] += len(self._place_predictions(predictions, fixture, context))
            except Exception as error:
                errors.append(f"{fixture.get('id')}: {_bounded_error(error)}")
        return {**counts, "item_count": counts["prediction_count"], "errors": errors[:20]}

    def _place_predictions(
        self,
        predictions: list[dict[str, Any]],
        fixture: dict[str, Any],
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        fixed_stake = float(getattr(self.settings, "automation_fixed_stake", 0) or 0)
        if fixed_stake > 0:
            context = {**context, "automation_fixed_stake": fixed_stake}
        bulk = getattr(self.bankroll_service, "place_for_predictions", None)
        if callable(bulk):
            return bulk(predictions, fixture, context)
        return [
            bet
            for prediction in predictions
            if (bet := self.bankroll_service.place_for_prediction(prediction, fixture, context))
        ]

    def _prediction_window(
        self,
        kickoff: datetime,
        now: datetime,
        refresh_state: dict[str, Any] | None = None,
        model_keys: list[str] | None = None,
    ) -> float | None:
        delta_minutes = (kickoff - now).total_seconds() / 60
        offset = next((item for item in sorted(self._prediction_offsets()) if delta_minutes <= item * 60), None)
        if offset is None or refresh_state is None:
            return offset
        token = self._prediction_window_token(offset)
        keys = model_keys or ["default"]
        return offset if any(not refresh_state.get(f"prediction_{token}_{key}_at") for key in keys) else None

    def _prediction_offsets(self) -> list[float]:
        raw = str(getattr(self.settings, "prediction_refresh_offsets_hours", "24,12,6,1,0.5"))
        values: set[float] = set()
        for item in raw.split(","):
            try:
                value = float(item.strip())
            except (TypeError, ValueError):
                continue
            if value > 0:
                values.add(value)
        return sorted(values or {24.0, 12.0, 6.0, 1.0, 0.5}, reverse=True)

    @staticmethod
    def _prediction_window_token(offset_hours: float) -> str:
        minutes = round(offset_hours * 60)
        return f"{minutes}m" if minutes < 60 else f"{minutes // 60}h"

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
        fetcher = getattr(self.evidence_provider, "fetch_public", None)
        if not callable(fetcher):
            raise RuntimeError("TheSportsDB 证据源不可用")
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
        reason: str | None = None,
    ) -> bool:
        if latest is None:
            return True
        lineup_confirmed = bool((context.get("lineup") or {}).get("confirmed"))
        if reason in (None, "lineup") and lineup_confirmed and latest.get("phase") != "confirmed_lineup":
            return True
        if reason in (None, "odds"):
            current_fingerprint = context.get("odds_fingerprint")
            if current_fingerprint and latest.get("odds_fingerprint") != current_fingerprint:
                model_key = str(latest.get("model_key") or (latest.get("ai") or {}).get("provider") or "default")
                marker = (context.get("automation_refresh") or {}).get(f"prediction_odds_{model_key}_at")
                last_reprediction = _as_utc(marker)
                min_interval = max(
                    1,
                    int(getattr(self.settings, "automation_odds_reprediction_interval_minutes", 15)),
                )
                if last_reprediction is None or now - last_reprediction >= timedelta(minutes=min_interval):
                    return True
        if reason in {"lineup", "odds"}:
            return False
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


def _has_fixture_squad(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    squad = value.get("squad")
    return isinstance(squad, list) and bool(squad)


def _snapshot_roster(snapshot: Any) -> list[dict[str, Any]]:
    if not isinstance(snapshot, dict):
        return []
    roster = snapshot.get("roster")
    return roster if isinstance(roster, list) else []


def _team_snapshot_needs_roster_refresh(
    snapshot: Any,
    now: datetime,
    ttl: timedelta,
) -> bool:
    if not isinstance(snapshot, dict):
        return True
    if _snapshot_roster(snapshot):
        return False
    # An empty roster is an incomplete snapshot, regardless of its timestamp.
    # Retry it immediately so historical empty records do not remain visible
    # until the normal roster TTL expires.
    return True


def _bounded_error(error: Exception) -> str:
    return (str(error).replace("\n", " ").replace("\r", " ")[:300] or error.__class__.__name__)


def _has_core_daily_evidence(context: dict[str, Any]) -> bool:
    """Use quota-free refreshes only after all daily evidence fields exist."""

    recent = context.get("recent_form") or {}
    availability = context.get("availability") or {}
    teams = context.get("teams") or {}
    return (
        len(recent.get("home") or []) >= 3
        and len(recent.get("away") or []) >= 3
        and bool(context.get("head_to_head"))
        and bool(availability.get("checked_at") or availability.get("updated_at") or availability.get("players"))
        and bool(teams.get("home"))
        and bool(teams.get("away"))
    )
