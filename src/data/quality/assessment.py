"""Fail-closed checks for business-critical Tier1 data contracts."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace
from datetime import date
from typing import Iterable

from src.data.point_in_time.contracts import DataEnvelope, FetchStatus

from .registry import capability_for
from .types import (
    CapabilityLevel,
    QualityAssessment,
    QualityIssue,
    QualitySeverity,
    VerificationStatus,
)


def _issue(
    code: str,
    severity: QualitySeverity,
    message: str,
    *,
    blocking: bool = False,
) -> QualityIssue:
    return QualityIssue(code, severity, message, blocking)


def _semantic_data_available(envelope: DataEnvelope) -> bool:
    return envelope.usable or (
        envelope.status == FetchStatus.EMPTY and envelope.data is not None
    )


def _validate_universe(data: Iterable, as_of_date: date) -> list[QualityIssue]:
    del as_of_date
    issues = []
    symbols = [str(item.symbol) for item in data]
    if not symbols:
        issues.append(
            _issue(
                "EMPTY_UNIVERSE",
                QualitySeverity.CRITICAL,
                "最终待筛股票池为空",
                blocking=True,
            )
        )
    duplicates = sorted(
        symbol for symbol, count in Counter(symbols).items() if count > 1
    )
    if duplicates:
        issues.append(
            _issue(
                "DUPLICATE_UNIVERSE_KEY",
                QualitySeverity.CRITICAL,
                f"股票池存在重复证券代码: {duplicates[:10]}",
                blocking=True,
            )
        )
    invalid = [symbol for symbol in symbols if not re.fullmatch(r"\d{6}", symbol)]
    if invalid:
        issues.append(
            _issue(
                "INVALID_SECURITY_CODE",
                QualitySeverity.CRITICAL,
                f"股票代码不是6位数字: {invalid[:10]}",
                blocking=True,
            )
        )
    invalid_exchange = sorted(
        {
            str(item.exchange)
            for item in data
            if str(item.exchange) not in {"SH", "SZ", "BJ"}
        }
    )
    if invalid_exchange:
        issues.append(
            _issue(
                "INVALID_EXCHANGE",
                QualitySeverity.HIGH,
                f"股票池包含未知交易所: {invalid_exchange}",
                blocking=True,
            )
        )
    return issues


def _validate_market(data, as_of_date: date) -> list[QualityIssue]:
    issues = []
    if data.price_date > as_of_date:
        issues.append(
            _issue(
                "FUTURE_PRICE_DATE",
                QualitySeverity.CRITICAL,
                f"行情日期{data.price_date}晚于as-of {as_of_date}",
                blocking=True,
            )
        )
    if data.close_price is None or data.close_price <= 0:
        issues.append(
            _issue(
                "INVALID_CLOSE_PRICE",
                QualitySeverity.HIGH,
                "收盘价缺失或非正",
                blocking=True,
            )
        )
    for field_name in ("market_cap", "total_shares"):
        value = getattr(data, field_name)
        if value is not None and value <= 0:
            issues.append(
                _issue(
                    f"INVALID_{field_name.upper()}",
                    QualitySeverity.HIGH,
                    f"{field_name}存在但非正",
                    blocking=True,
                )
            )
    if data.supplier_pe_ttm is not None and data.supplier_pe_ttm <= 0:
        issues.append(
            _issue(
                "NON_POSITIVE_SUPPLIER_PE",
                QualitySeverity.MEDIUM,
                "供应商PE(TTM)非正，将由业务层按缺失处理",
            )
        )
    return issues


def _validate_financials(data: Iterable, as_of_date: date) -> list[QualityIssue]:
    facts = list(data)
    issues = []
    if not facts:
        issues.append(
            _issue(
                "EMPTY_FINANCIAL_FACT_SET",
                QualitySeverity.HIGH,
                "财务接口返回成功但没有任何报告期事实",
                blocking=True,
            )
        )
    periods = [fact.report_period for fact in facts]
    duplicates = sorted(
        period for period, count in Counter(periods).items() if count > 1
    )
    if duplicates:
        issues.append(
            _issue(
                "DUPLICATE_FINANCIAL_GRAIN",
                QualitySeverity.CRITICAL,
                f"同一报告期存在多个未消歧版本: {[str(item) for item in duplicates]}",
                blocking=True,
            )
        )
    valid_quarter_ends = {(3, 31), (6, 30), (9, 30), (12, 31)}
    for fact in facts:
        if (fact.report_period.month, fact.report_period.day) not in valid_quarter_ends:
            issues.append(
                _issue(
                    "NON_STANDARD_REPORT_PERIOD",
                    QualitySeverity.HIGH,
                    f"非标准季度报告期: {fact.report_period}",
                    blocking=True,
                )
            )
        if fact.report_period > as_of_date:
            issues.append(
                _issue(
                    "FUTURE_REPORT_PERIOD",
                    QualitySeverity.CRITICAL,
                    f"报告期{fact.report_period}晚于as-of {as_of_date}",
                    blocking=True,
                )
            )
        if fact.announcement_date > as_of_date:
            issues.append(
                _issue(
                    "FUTURE_ANNOUNCEMENT",
                    QualitySeverity.CRITICAL,
                    f"公告日{fact.announcement_date}晚于as-of {as_of_date}",
                    blocking=True,
                )
            )
        if fact.revision_at is not None and fact.revision_at.date() > as_of_date:
            issues.append(
                _issue(
                    "FUTURE_REVISION",
                    QualitySeverity.CRITICAL,
                    f"修订时间{fact.revision_at.date()}晚于as-of {as_of_date}",
                    blocking=True,
                )
            )
        if fact.operating_revenue is None and fact.parent_net_profit is None:
            issues.append(
                _issue(
                    "EMPTY_FINANCIAL_FACT",
                    QualitySeverity.MEDIUM,
                    f"{fact.report_period}营业收入和归母净利润均缺失",
                )
            )
    return issues


def _validate_dividends(data, as_of_date: date) -> list[QualityIssue]:
    issues = []
    for event in data.events:
        if event.ex_date > as_of_date:
            issues.append(
                _issue(
                    "FUTURE_DIVIDEND_EVENT",
                    QualitySeverity.CRITICAL,
                    f"除权日{event.ex_date}晚于as-of {as_of_date}",
                    blocking=True,
                )
            )
        if event.announcement_date and event.announcement_date > as_of_date:
            issues.append(
                _issue(
                    "FUTURE_DIVIDEND_ANNOUNCEMENT",
                    QualitySeverity.CRITICAL,
                    f"分红可得日{event.announcement_date}晚于as-of {as_of_date}",
                    blocking=True,
                )
            )
        if event.raw_cash_per_share_pre_tax < 0:
            issues.append(
                _issue(
                    "NEGATIVE_CASH_DIVIDEND",
                    QualitySeverity.CRITICAL,
                    "税前每股现金分红为负",
                    blocking=True,
                )
            )
    for action in data.actions:
        if action.effective_date > as_of_date:
            issues.append(
                _issue(
                    "FUTURE_CORPORATE_ACTION",
                    QualitySeverity.CRITICAL,
                    f"公司行动生效日{action.effective_date}晚于as-of {as_of_date}",
                    blocking=True,
                )
            )
        if action.share_factor <= 0:
            issues.append(
                _issue(
                    "INVALID_SHARE_FACTOR",
                    QualitySeverity.CRITICAL,
                    "送转股本调整因子非正",
                    blocking=True,
                )
            )
    return issues


def _validate_risk(data, as_of_date: date) -> list[QualityIssue]:
    issues = []
    if data.effective_date and data.effective_date > as_of_date:
        issues.append(
            _issue(
                "FUTURE_RISK_STATUS",
                QualitySeverity.CRITICAL,
                f"风险状态生效日{data.effective_date}晚于as-of {as_of_date}",
                blocking=True,
            )
        )
    if data.is_risk_warning is None:
        issues.append(
            _issue(
                "UNKNOWN_RISK_STATUS",
                QualitySeverity.HIGH,
                "ST/退市风险状态未知",
                blocking=True,
            )
        )
    return issues


VALIDATORS = {
    "universe": _validate_universe,
    "market": _validate_market,
    "financial_statements": _validate_financials,
    "dividend_and_actions": _validate_dividends,
    "risk_warning_status": _validate_risk,
}


def assess_envelope(
    field_group: str, envelope: DataEnvelope, as_of_date: date
) -> QualityAssessment:
    capability = capability_for(envelope.provider, field_group)
    semantic_data = _semantic_data_available(envelope)
    verification = (
        VerificationStatus.SINGLE_SOURCE
        if semantic_data
        else VerificationStatus.UNVERIFIED
    )
    issues: list[QualityIssue] = []

    if capability == CapabilityLevel.UNSUPPORTED and semantic_data:
        issues.append(
            _issue(
                "UNSUPPORTED_SOURCE_CONTRACT",
                QualitySeverity.CRITICAL,
                f"{envelope.provider}不允许为{field_group}提供可用事实",
                blocking=True,
            )
        )
    elif capability == CapabilityLevel.LIMITED and semantic_data:
        hard_condition = field_group in {
            "dividend_and_actions",
            "risk_warning_status",
        }
        issues.append(
            _issue(
                "LIMITED_SOURCE_CAPABILITY",
                QualitySeverity.HIGH if hard_condition else QualitySeverity.LOW,
                (
                    f"{envelope.provider}对{field_group}仅具有限定覆盖，"
                    "不能据此判定硬条件通过"
                    if hard_condition
                    else f"{envelope.provider}对{field_group}仅具有限定覆盖"
                ),
                blocking=hard_condition,
            )
        )
    elif capability == CapabilityLevel.UNKNOWN and semantic_data:
        issues.append(
            _issue(
                "UNREGISTERED_SOURCE",
                QualitySeverity.LOW,
                f"{envelope.provider}未登记来源能力，仅按单源使用",
            )
        )

    if envelope.status == FetchStatus.SCHEMA_ERROR:
        issues.append(
            _issue(
                "UPSTREAM_SCHEMA_ERROR",
                QualitySeverity.CRITICAL,
                envelope.error_message or "上游Schema不满足契约",
                blocking=True,
            )
        )
    elif envelope.status == FetchStatus.ERROR:
        issues.append(
            _issue(
                "UPSTREAM_FETCH_ERROR",
                QualitySeverity.HIGH,
                envelope.error_message or "上游取数失败",
                blocking=True,
            )
        )
    elif envelope.status == FetchStatus.EMPTY and envelope.data is None:
        issues.append(
            _issue(
                "REQUIRED_DATA_EMPTY",
                QualitySeverity.MEDIUM,
                f"{field_group}没有可用数据",
            )
        )

    if envelope.available_at and envelope.available_at > as_of_date:
        issues.append(
            _issue(
                "FUTURE_AVAILABLE_AT",
                QualitySeverity.CRITICAL,
                f"数据可得日{envelope.available_at}晚于as-of {as_of_date}",
                blocking=True,
            )
        )

    validator = VALIDATORS.get(field_group)
    if semantic_data and validator is not None:
        issues.extend(validator(envelope.data, as_of_date))

    if any(issue.blocking for issue in issues):
        verification = VerificationStatus.UNVERIFIED

    return QualityAssessment(
        field_group=field_group,
        provider=envelope.provider,
        capability=capability,
        verification_status=verification,
        issues=tuple(issues),
    )


def gate_envelope(
    envelope: DataEnvelope, assessment: QualityAssessment
) -> DataEnvelope:
    warnings = [
        *envelope.quality_warnings,
        *assessment.warning_messages(),
    ]
    if assessment.blocking and _semantic_data_available(envelope):
        blocking_messages = [
            issue.message for issue in assessment.issues if issue.blocking
        ]
        return replace(
            envelope,
            status=FetchStatus.SCHEMA_ERROR,
            data=None,
            error_type="DATA_QUALITY_GATE",
            error_message="；".join(blocking_messages),
            quality_warnings=warnings,
        )
    return replace(envelope, quality_warnings=warnings)
