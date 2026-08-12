"""Stage A Tier1 v2 orchestration."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import replace
from datetime import date, timedelta
from typing import Iterable, Optional

from src.data.point_in_time.contracts import (
    DataEnvelope,
    DividendBundle,
    FetchStatus,
    UniverseItem,
)
from src.data.quality import assess_envelope, gate_envelope
from src.strategies.golden_pit.config import Tier1Config
from src.strategies.golden_pit.persistence.tier1_repository import Tier1Repository
from src.strategies.golden_pit.versioning import build_release_manifest

from .contracts import MarketSnapshot, Tier1Decision
from .decision import DecisionInput, evaluate_tier1
from .metrics import (
    DividendCalculation,
    calculate_dividend_ttm,
    compute_self_pe_ttm,
    select_pe_ttm,
)
from .quarterly import (
    build_quarterly_series,
    recent_quarter_window,
    ttm_parent_net_profit,
)

logger = logging.getLogger(__name__)


class RunLeaseLostError(RuntimeError):
    """Raised when a worker can no longer prove exclusive ownership of a run."""


class _RunLeaseHeartbeat:
    """Renew the run lease while a slow provider call is still in progress."""

    def __init__(
        self,
        repository: Tier1Repository,
        run_id: str,
        worker_token: str,
        *,
        interval_seconds: float = 30.0,
    ) -> None:
        self.repository = repository
        self.run_id = run_id
        self.worker_token = worker_token
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._failure: BaseException | None = None
        self._thread = threading.Thread(
            target=self._run,
            name=f"run-lease-{run_id[:8]}",
            daemon=True,
        )

    def start(self) -> None:
        self.repository.heartbeat_run_lease(self.run_id, self.worker_token)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.repository.heartbeat_run_lease(self.run_id, self.worker_token)
            except BaseException as exc:  # pragma: no cover - timing boundary
                self._failure = exc
                self._stop.set()
                return

    def check(self) -> None:
        if self._failure is not None:
            raise RunLeaseLostError(
                "运行租约续期失败，已停止写入以避免并发冲突"
            ) from self._failure

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=max(1.0, self.interval_seconds + 1.0))


class Tier1Pipeline:
    def __init__(
        self,
        provider,
        repository: Tier1Repository,
        config: Optional[Tier1Config] = None,
    ):
        self.provider = provider
        self.repository = repository
        self.config = config or Tier1Config()

    def run(
        self,
        as_of_date: date,
        *,
        symbols: Optional[Iterable[str]] = None,
        universe_items: Optional[Iterable[UniverseItem]] = None,
        limit: Optional[int] = None,
    ) -> dict:
        run_id = self.repository.begin_run(as_of_date, self.config)
        run_errors: list[str] = []

        if universe_items is not None:
            universe = list(universe_items)
        else:
            universe_envelope = self.provider.get_universe(as_of_date)
            universe_envelope, _ = self._record_and_gate(
                run_id, None, "universe", universe_envelope, as_of_date
            )
            if universe_envelope.usable:
                universe = list(universe_envelope.data)
            elif symbols:
                universe = [
                    UniverseItem(
                        symbol=str(symbol).zfill(6),
                        name=str(symbol).zfill(6),
                        exchange=self.provider.exchange_for(str(symbol).zfill(6)),
                    )
                    for symbol in symbols
                ]
                run_errors.append("股票池接口失败，使用显式symbols")
            else:
                self.repository.finish_run(
                    run_id,
                    status="FAILED",
                    universe_size=0,
                    errors=[universe_envelope.error_message or "无法获取股票池"],
                )
                return {
                    "run_id": run_id,
                    "status": "FAILED",
                    "summary": {},
                    "data_quality": self.repository.quality_summary(run_id),
                }

        if symbols:
            wanted = {str(symbol).zfill(6) for symbol in symbols}
            existing = {item.symbol for item in universe}
            universe = [item for item in universe if item.symbol in wanted]
            universe.extend(
                UniverseItem(
                    symbol=symbol,
                    name=symbol,
                    exchange=self.provider.exchange_for(symbol),
                )
                for symbol in sorted(wanted - existing)
            )

        normalized_universe = DataEnvelope(
            status=FetchStatus.SUCCESS,
            data=universe,
            provider="PIPELINE_INPUT",
            endpoint="normalized_final_universe",
            request={
                "as_of_date": as_of_date.isoformat(),
                "symbols_explicit": bool(symbols),
                "universe_items_explicit": universe_items is not None,
                "row_count": len(universe),
            },
            available_at=as_of_date,
            row_count=len(universe),
        )
        normalized_universe, _ = self._record_and_gate(
            run_id, None, "universe", normalized_universe, as_of_date
        )
        if not normalized_universe.usable:
            self.repository.finish_run(
                run_id,
                status="FAILED",
                universe_size=0,
                errors=[
                    normalized_universe.error_message or "最终股票池未通过质量闸门"
                ],
            )
            return {
                "run_id": run_id,
                "status": "FAILED",
                "summary": {},
                "data_quality": self.repository.quality_summary(run_id),
            }
        universe = list(normalized_universe.data)
        if limit is not None:
            universe = universe[: max(0, limit)]
        self.repository.save_run_universe(run_id, universe, snapshot_source="CAPTURED")
        worker_token = self.repository.acquire_run_lease(
            run_id, allow_recent_activity=True
        )
        return self._process_items(
            run_id,
            as_of_date,
            universe,
            trigger_type="INITIAL",
            worker_token=worker_token,
            prior_errors=run_errors,
        )

    def resume(
        self,
        run_id: str,
        *,
        mode: str = "unfinished",
        symbols: Optional[Iterable[str]] = None,
    ) -> dict:
        """Resume unfinished work or retry evidence-deficient symbols in-place."""
        run = self.repository.run_record(run_id)
        if run is None:
            raise ValueError(f"未知Tier1 run_id: {run_id}")
        if str(run["calculation_version"]) != self.config.calculation_version:
            raise ValueError("运行计算版本与当前代码不一致，禁止混合口径续跑")
        stored_manifest = json.loads(run.get("release_manifest_json") or "{}")
        current_manifest = build_release_manifest(self.config)
        if stored_manifest.get("strategy_fingerprint") and stored_manifest.get(
            "strategy_fingerprint"
        ) != current_manifest.get("strategy_fingerprint"):
            raise ValueError("策略代码或规则资源已变化，禁止在原运行中混合口径续跑")
        as_of_date = date.fromisoformat(str(run["as_of_date"]))
        if not self.repository.has_run_universe(run_id):
            envelope = self.provider.get_universe(as_of_date)
            envelope, _ = self._record_and_gate(
                run_id, None, "universe", envelope, as_of_date
            )
            if not envelope.usable:
                raise ValueError("旧运行缺少股票池快照，且无法从原时点重建")
            reconstructed = list(envelope.data)
            expected = self.repository.legacy_universe_size(run_id)
            reconstructed_symbols = {item.symbol for item in reconstructed}
            known_symbols = self.repository.decision_symbols(run_id)
            if (
                expected is None
                or len(reconstructed) != expected
                or not known_symbols.issubset(reconstructed_symbols)
            ):
                raise ValueError(
                    "旧运行股票池无法通过数量及已处理代码校验，禁止不精确续跑："
                    f"记录={expected}，重建={len(reconstructed)}，"
                    f"不匹配已处理代码={len(known_symbols - reconstructed_symbols)}"
                )
            self.repository.save_run_universe(
                run_id, reconstructed, snapshot_source="RECONSTRUCTED_LEGACY"
            )
            self.repository.backfill_run_universe_progress(run_id)

        worker_token = self.repository.acquire_run_lease(run_id)
        targets = self.repository.resume_targets(
            run_id, mode=mode, symbols=symbols
        )
        return self._process_items(
            run_id,
            as_of_date,
            targets,
            trigger_type="RESUME" if mode == "unfinished" else "DATA_RETRY",
            worker_token=worker_token,
            prior_errors=[],
        )

    def _process_items(
        self,
        run_id: str,
        as_of_date: date,
        universe: list[UniverseItem],
        *,
        trigger_type: str,
        worker_token: str,
        prior_errors: list[str],
    ) -> dict:
        run_errors = list(prior_errors)
        lease_heartbeat = _RunLeaseHeartbeat(
            self.repository, run_id, worker_token
        )
        lease_heartbeat.start()
        try:
            for index, item in enumerate(universe, start=1):
                lease_heartbeat.check()
                attempt_id = self.repository.begin_item_attempt(
                    run_id, item.symbol, trigger_type
                )
                attempt_error = None
                decision = None
                lease_lost = False
                try:
                    decision = self._screen_stock(run_id, item, as_of_date)
                    lease_heartbeat.check()
                    self.repository.save_decision(
                        run_id, decision, attempt_id=attempt_id
                    )
                    logger.info(
                        "Tier1 v2 %s/%s %s %s/%s trigger=%s",
                        index,
                        len(universe),
                        item.symbol,
                        decision.screen_status,
                        decision.data_status.value,
                        trigger_type,
                    )
                except RunLeaseLostError as exc:
                    attempt_error = exc
                    lease_lost = True
                    raise
                except Exception as exc:
                    attempt_error = exc
                    logger.exception("Tier1 v2 单股处理失败 %s", item.symbol)
                    run_errors.append(
                        f"{item.symbol}: {type(exc).__name__}: {exc}"
                    )
                    decision = evaluate_tier1(
                        DecisionInput(
                            symbol=item.symbol,
                            stock_name=item.name,
                            as_of_date=as_of_date,
                            price_date=None,
                            selected_pe_ttm=None,
                            supplier_pe_ttm=None,
                            self_pe_ttm=None,
                            pe_selection_method=None,
                            dividend_yield_ttm=None,
                            dividend_ttm_raw_per_share=None,
                            dividend_ttm_adjusted_per_share=None,
                            risk_warning=None,
                            quarterly_window=[],
                            error_fields=["pipeline"],
                        ),
                        self.config,
                    )
                    lease_heartbeat.check()
                    self.repository.save_decision(
                        run_id, decision, attempt_id=attempt_id
                    )
                except BaseException as exc:
                    attempt_error = exc
                    raise
                finally:
                    if not lease_lost:
                        self.repository.finish_item_attempt(
                            attempt_id,
                            decision_status=(
                                decision.screen_status if decision else None
                            ),
                            data_status=(
                                decision.data_status.value if decision else None
                            ),
                            error=attempt_error,
                        )

            lease_heartbeat.check()
            run_status = (
                "FINISHED_WITH_ERRORS"
                if run_errors or self.repository.has_retryable_items(run_id)
                else "FINISHED"
            )
            all_items = self.repository.load_run_universe(run_id)
            self.repository.finish_run(
                run_id,
                status=run_status,
                universe_size=len(all_items),
                price_dates=self.repository.decision_price_dates(run_id),
                errors=run_errors,
            )
            return {
                "run_id": run_id,
                "status": run_status,
                "universe_size": len(all_items),
                "processed_count": len(universe),
                "summary": self.repository.summary(run_id),
                "data_quality": self.repository.quality_summary(run_id),
                "errors": run_errors,
            }
        except BaseException as exc:
            self.repository.mark_run_interrupted(run_id, exc)
            raise
        finally:
            lease_heartbeat.stop()
            self.repository.release_run_lease(run_id, worker_token)

    def _record_and_gate(
        self,
        run_id: str,
        symbol: Optional[str],
        field_group: str,
        envelope: DataEnvelope,
        as_of_date: date,
    ) -> tuple[DataEnvelope, int]:
        assessment = assess_envelope(field_group, envelope, as_of_date)
        observation_id = self.repository.save_observation(
            run_id, symbol, field_group, envelope
        )
        self.repository.save_quality_assessment(
            run_id, symbol, observation_id, assessment
        )
        return gate_envelope(envelope, assessment), observation_id

    @staticmethod
    def _is_error(envelope: DataEnvelope) -> bool:
        return envelope.status in {FetchStatus.ERROR, FetchStatus.SCHEMA_ERROR}

    def _screen_stock(
        self, run_id: str, item: UniverseItem, as_of_date: date
    ) -> Tier1Decision:
        errors: list[str] = []
        skipped: list[str] = []
        warnings: list[str] = []
        market: Optional[MarketSnapshot] = None
        quarterly_series = []
        trend_window = []
        dividend_calculation = DividendCalculation(None, None, None, ())
        risk_warning: Optional[bool] = None

        market_env = self.provider.get_market_snapshot(item.symbol, as_of_date)
        market_env, market_obs = self._record_and_gate(
            run_id, item.symbol, "market", market_env, as_of_date
        )
        warnings.extend(market_env.quality_warnings)
        if market_env.usable:
            market = replace(market_env.data, source_observation_id=market_obs)
            self.repository.save_lineage(
                run_id,
                item.symbol,
                "supplier_pe_ttm",
                source_observation_id=market_obs,
                available_at=market.price_date,
                raw_value=market.supplier_pe_ttm,
                calculated_value=market.supplier_pe_ttm,
                calculation_note=f"{market.source}供应商PE(TTM)",
            )
            self.repository.save_lineage(
                run_id,
                item.symbol,
                "close_price",
                source_observation_id=market_obs,
                available_at=market.price_date,
                raw_value=market.close_price,
                calculated_value=market.close_price,
                calculation_note="as_of_date及之前最近交易日收盘价",
            )
        elif self._is_error(market_env):
            errors.append("market_snapshot")

        supplier_pe = market.supplier_pe_ttm if market else None
        historical = as_of_date < self.provider.today - timedelta(
            days=self.config.current_supplier_window_days
        )
        initial_pe = select_pe_ttm(
            supplier_pe_ttm=supplier_pe,
            self_pe_ttm=None,
            historical=historical,
            mismatch_warning_ratio=self.config.pe_mismatch_warning_ratio,
        )

        must_fetch_financials = (
            historical
            or initial_pe.selected is None
            or (initial_pe.selected < self.config.max_pe_ttm)
        )
        self_pe = None
        financial_env = None
        financial_obs = None
        if must_fetch_financials:
            financial_env = self.provider.get_financial_facts(item.symbol, as_of_date)
            financial_env, financial_obs = self._record_and_gate(
                run_id,
                item.symbol,
                "financial_statements",
                financial_env,
                as_of_date,
            )
            warnings.extend(financial_env.quality_warnings)
            if financial_env.usable:
                facts = [
                    replace(fact, source_observation_id=financial_obs)
                    for fact in financial_env.data
                ]
                self.repository.save_financial_facts(run_id, facts, financial_obs)
                quarterly_series = build_quarterly_series(facts, as_of_date)
                self.repository.save_quarterly_series(run_id, quarterly_series)
                trend_window = recent_quarter_window(
                    quarterly_series, self.config.trend_quarters
                )
                ttm_profit = ttm_parent_net_profit(quarterly_series)
                self_pe = compute_self_pe_ttm(
                    market.market_cap if market else None, ttm_profit
                )
                self.repository.save_lineage(
                    run_id,
                    item.symbol,
                    "self_pe_ttm",
                    source_observation_id=financial_obs,
                    source_period=trend_window[-1].quarter.isoformat()
                    if trend_window
                    else None,
                    available_at=financial_env.available_at,
                    raw_value={
                        "market_cap": market.market_cap if market else None,
                        "ttm_parent_net_profit": ttm_profit,
                    },
                    calculated_value=self_pe,
                    calculation_note="点时总市值/截至as_of已公告最近连续四个单季度归母净利润之和",
                )
            elif self._is_error(financial_env):
                errors.append("financial_statements")
        else:
            skipped.extend(
                [
                    "financial_statements_after_known_pe_fail",
                    "quarterly_trend_after_known_pe_fail",
                    "self_pe_ttm_after_known_pe_fail",
                ]
            )

        pe_selection = select_pe_ttm(
            supplier_pe_ttm=supplier_pe,
            self_pe_ttm=self_pe,
            historical=historical,
            mismatch_warning_ratio=self.config.pe_mismatch_warning_ratio,
        )
        warnings.extend(pe_selection.warnings)

        known_pe_fail = (
            pe_selection.selected is not None
            and not pe_selection.selected < self.config.max_pe_ttm
        )
        dividend_env = None
        dividend_obs = None
        if known_pe_fail:
            skipped.extend(
                [
                    "dividend_yield_after_known_pe_fail",
                    "risk_warning_after_known_pe_fail",
                ]
            )
        else:
            dividend_env = self.provider.get_dividend_bundle(item.symbol, as_of_date)
            dividend_env, dividend_obs = self._record_and_gate(
                run_id,
                item.symbol,
                "dividend_and_actions",
                dividend_env,
                as_of_date,
            )
            warnings.extend(dividend_env.quality_warnings)
            bundle: Optional[DividendBundle] = None
            if dividend_env.usable:
                bundle = dividend_env.data
            elif (
                dividend_env.status == FetchStatus.EMPTY
                and dividend_env.data is not None
            ):
                bundle = dividend_env.data
            elif self._is_error(dividend_env):
                errors.append("dividend_and_actions")
            if bundle is not None:
                events = [
                    replace(event, source_observation_id=dividend_obs)
                    for event in bundle.events
                ]
                actions = [
                    replace(action, source_observation_id=dividend_obs)
                    for action in bundle.actions
                ]
                bundle = DividendBundle(tuple(events), tuple(actions))
                dividend_calculation = calculate_dividend_ttm(
                    events=events,
                    actions=actions,
                    as_of_date=as_of_date,
                    close_price=market.close_price if market else None,
                )
                self.repository.save_dividends(
                    run_id, bundle, dividend_calculation, dividend_obs
                )
                self.repository.save_lineage(
                    run_id,
                    item.symbol,
                    "dividend_yield_ttm",
                    source_observation_id=dividend_obs,
                    available_at=as_of_date,
                    raw_value={
                        "raw_cash_per_share": dividend_calculation.raw_per_share,
                        "close_price": market.close_price if market else None,
                    },
                    calculated_value=dividend_calculation.dividend_yield_ttm,
                    calculation_note="税前已实施现金分红，按除权日TTM窗口并按送转行动调整到as_of股份口径",
                )

        known_dividend_fail = (
            dividend_calculation.dividend_yield_ttm is not None
            and not dividend_calculation.dividend_yield_ttm
            > self.config.min_dividend_yield_ttm
        )
        if not known_pe_fail and not known_dividend_fail:
            risk_env = self.provider.get_risk_warning_status(
                item.symbol, item.name, as_of_date
            )
            risk_env, risk_obs = self._record_and_gate(
                run_id,
                item.symbol,
                "risk_warning_status",
                risk_env,
                as_of_date,
            )
            warnings.extend(risk_env.quality_warnings)
            if risk_env.usable:
                risk = replace(risk_env.data, source_observation_id=risk_obs)
                risk_warning = risk.is_risk_warning
                self.repository.save_risk_status(run_id, risk, risk_obs)
                self.repository.save_lineage(
                    run_id,
                    item.symbol,
                    "risk_warning_status",
                    source_observation_id=risk_obs,
                    available_at=risk.effective_date or as_of_date,
                    raw_value=risk.security_name,
                    calculated_value=risk.is_risk_warning,
                    calculation_note=f"按{risk.source}在as_of_date的有效风险状态判定",
                )
            elif self._is_error(risk_env):
                errors.append("risk_warning_status")
        elif not known_pe_fail:
            skipped.append("risk_warning_after_known_dividend_fail")

        if financial_env is None and not known_pe_fail:
            financial_env = self.provider.get_financial_facts(item.symbol, as_of_date)
            financial_env, financial_obs = self._record_and_gate(
                run_id,
                item.symbol,
                "financial_statements",
                financial_env,
                as_of_date,
            )
            warnings.extend(financial_env.quality_warnings)
            if financial_env.usable:
                facts = [
                    replace(fact, source_observation_id=financial_obs)
                    for fact in financial_env.data
                ]
                self.repository.save_financial_facts(run_id, facts, financial_obs)
                quarterly_series = build_quarterly_series(facts, as_of_date)
                self.repository.save_quarterly_series(run_id, quarterly_series)
                trend_window = recent_quarter_window(
                    quarterly_series, self.config.trend_quarters
                )
            elif self._is_error(financial_env):
                errors.append("financial_statements")

        if known_dividend_fail and not trend_window:
            skipped.append("quarterly_trend_after_known_dividend_fail")

        decision = evaluate_tier1(
            DecisionInput(
                symbol=item.symbol,
                stock_name=item.name,
                as_of_date=as_of_date,
                price_date=market.price_date if market else None,
                selected_pe_ttm=pe_selection.selected,
                supplier_pe_ttm=pe_selection.supplier,
                self_pe_ttm=pe_selection.self_computed,
                pe_selection_method=pe_selection.method,
                dividend_yield_ttm=dividend_calculation.dividend_yield_ttm,
                dividend_ttm_raw_per_share=dividend_calculation.raw_per_share,
                dividend_ttm_adjusted_per_share=dividend_calculation.adjusted_per_share,
                risk_warning=risk_warning,
                quarterly_window=trend_window,
                error_fields=errors,
                skipped_fields=skipped,
                quality_warnings=warnings,
            ),
            self.config,
        )
        return decision
