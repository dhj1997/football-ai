"""One versioned forecast and bet-opinion contract shared by every LLM provider."""

import json
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PROMPT_CONTRACT_VERSION = "football-forecast-v5"
EVIDENCE_CONTRACT_VERSION = "fixture-evidence-v3"


class OutcomeProbabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")
    home: float = Field(ge=0, le=1)
    draw: float = Field(ge=0, le=1)
    away: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_total(self) -> "OutcomeProbabilities":
        if abs(self.home + self.draw + self.away - 1) > 0.02:
            raise ValueError("1X2 probabilities must sum to 1")
        return self


class AsianHandicapForecast(BaseModel):
    model_config = ConfigDict(extra="forbid")
    available: bool
    line: float | None
    home_cover_probability: float | None = Field(ge=0, le=1)
    away_cover_probability: float | None = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_availability(self) -> "AsianHandicapForecast":
        probabilities = (self.home_cover_probability, self.away_cover_probability)
        if not self.available and (self.line is not None or any(value is not None for value in probabilities)):
            raise ValueError("unavailable Asian handicap must use null line and probabilities")
        if self.available and (self.line is None or any(value is None for value in probabilities)):
            raise ValueError("available Asian handicap requires a line and both cover probabilities")
        if self.available:
            total = sum(value or 0 for value in probabilities)
            if total <= 0:
                raise ValueError("Asian handicap cover probabilities must have positive mass")
            self.home_cover_probability = round(float(self.home_cover_probability or 0) / total, 6)
            self.away_cover_probability = round(float(self.away_cover_probability or 0) / total, 6)
        return self


class PlayerEvidenceAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key_available_players: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(max_length=8)
    key_absent_players: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(max_length=8)
    replacement_gap: str = Field(min_length=1, max_length=300)
    attack_impact: str = Field(min_length=1, max_length=300)
    defense_impact: str = Field(min_length=1, max_length=300)


class BetRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["bet", "no_bet"]
    market: Literal["1x2", "asian_handicap", "no_bet"]
    selection: Literal["home", "draw", "away", "home_handicap", "away_handicap", "none"]
    reason: str = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def validate_selection(self) -> "BetRecommendation":
        if self.status == "no_bet":
            if self.market != "no_bet" or self.selection != "none":
                raise ValueError("no_bet recommendation must use no_bet/none")
            return self
        valid = {
            "1x2": {"home", "draw", "away"},
            "asian_handicap": {"home_handicap", "away_handicap"},
        }
        if self.selection not in valid.get(self.market, set()):
            raise ValueError("bet recommendation selection does not match its market")
        return self


class ForecastAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    probabilities: OutcomeProbabilities
    predicted_outcome: Literal["home", "draw", "away"]
    forecast_confidence: float = Field(ge=0, le=1)
    asian_handicap_forecast: AsianHandicapForecast
    player_analysis: PlayerEvidenceAnalysis
    bet_recommendation: BetRecommendation
    analysis_summary: str = Field(min_length=1, max_length=600)
    risk_factors: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(min_length=1, max_length=8)
    missing_evidence: list[Annotated[str, Field(min_length=1, max_length=160)]] = Field(max_length=12)

    @model_validator(mode="after")
    def validate_outcome(self) -> "ForecastAssessment":
        probabilities = self.probabilities.model_dump()
        if self.predicted_outcome != max(probabilities, key=probabilities.get):
            raise ValueError("predicted outcome must match the highest 1X2 probability")
        return self


@dataclass(frozen=True)
class PromptContract:
    version: str = PROMPT_CONTRACT_VERSION
    evidence_version: str = EVIDENCE_CONTRACT_VERSION

    @property
    def system_message(self) -> str:
        return (
            "你是足球赛前预测模型，只能使用输入证据，不得补造事实。你需要输出1X2概率、亚洲让球"
            "覆盖概率、球员证据解释、风险说明，以及是否值得进入后端校验的下注观点和唯一市场方向。"
            "下注观点不是最终执行决定；不得计算赔率EV、不得输出仓位，也不得覆盖后端赔率和风控。"
            "必须逐项分析关键可用球员、关键缺阵球员、预计替补差距以及进攻和防守影响。"
            "不得按伤停人数直接扣减球队整体实力；必须依据球员角色、预计分钟、贡献和替补差值。"
            "首发未确认只能作为不确定性，不得仅凭这一项直接输出不下注；应结合预计首发和预计分钟判断。"
            "身价只能作为带来源和时效的弱证据，缺失时不得按0处理。所有面向用户的文本、球队名和"
            "球员名必须使用输入中的简体中文。返回内容必须严格符合给定JSON Schema，不要输出Markdown。"
        )

    def schema(self) -> dict[str, Any]:
        return ForecastAssessment.model_json_schema()

    def messages(self, model_input: dict[str, Any]) -> list[dict[str, str]]:
        payload = {
            "prompt_contract_version": self.version,
            "evidence_version": self.evidence_version,
            "json_schema": self.schema(),
            "evidence": model_input,
        }
        return [
            {"role": "system", "content": self.system_message},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)},
        ]


DEFAULT_PROMPT_CONTRACT = PromptContract()


def validate_forecast_assessment(assessment: ForecastAssessment, model_input: dict[str, Any]) -> None:
    handicap = assessment.asian_handicap_forecast
    odds = model_input.get("odds")
    line = odds.get("asian_handicap") if isinstance(odds, dict) else None
    if line is None and handicap.available:
        raise ValueError("Asian handicap forecast cannot be available without an evidence line")
    if handicap.available and abs(float(handicap.line) - float(line)) > 1e-8:
        raise ValueError("Asian handicap forecast line does not match the evidence")
    fields = [
        assessment.analysis_summary,
        assessment.asian_handicap_forecast.reason,
        assessment.player_analysis.replacement_gap,
        assessment.player_analysis.attack_impact,
        assessment.player_analysis.defense_impact,
        assessment.bet_recommendation.reason,
        *assessment.player_analysis.key_available_players,
        *assessment.player_analysis.key_absent_players,
        *assessment.risk_factors,
        *assessment.missing_evidence,
    ]
    if any(text and not any("\u3400" <= character <= "\u9fff" for character in text) for text in fields):
        raise ValueError("Model user-facing text must be written in Chinese")
    player_names = [
        *assessment.player_analysis.key_available_players,
        *assessment.player_analysis.key_absent_players,
    ]
    if any(any("A" <= character <= "Z" or "a" <= character <= "z" for character in name) for name in player_names):
        raise ValueError("Model player names must not contain supplier Latin names")
