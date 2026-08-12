import pytest

from src.artifacts import ArtifactRepository
from src.trading import ShadowOMS


def test_shadow_oms_requires_feasible_portfolio_human_and_emergency_control(tmp_path):
    db_path = tmp_path / "shadow.db"
    artifacts = ArtifactRepository(db_path)
    artifacts.migrate()
    artifacts.append(
        artifact_id="portfolio-1",
        artifact_type="PORTFOLIO",
        status="FEASIBLE",
        payload={"weights": {"security-1": 1.0}},
        created_by="optimizer",
    )
    oms = ShadowOMS(db_path)
    oms.enable(actor="trader", reason="开始 Shadow 验证")
    with pytest.raises(PermissionError, match="AI 不得"):
        oms.create_orders(
            "portfolio-1",
            [{"security_id": "security-1", "side": "BUY", "quantity": 100}],
            actor="ai:deepseek",
        )
    order_id = oms.create_orders(
        "portfolio-1",
        [{"security_id": "security-1", "side": "BUY", "quantity": 100}],
        actor="trader",
    )[0]
    assert oms.transition(order_id, "APPROVED", actor="risk-manager")["status"] == "APPROVED"

    oms.emergency_stop(actor="risk-manager", reason="数据源异常")
    with pytest.raises(PermissionError, match="紧急停止"):
        oms.transition(order_id, "SUBMITTED", actor="trader")


def test_shadow_oms_preserves_append_only_order_history(tmp_path):
    db_path = tmp_path / "history.db"
    artifacts = ArtifactRepository(db_path)
    artifacts.migrate()
    artifacts.append(
        artifact_id="portfolio",
        artifact_type="PORTFOLIO",
        status="VALIDATED",
        payload={},
        created_by="optimizer",
    )
    oms = ShadowOMS(db_path)
    oms.enable(actor="operator", reason="test")
    order_id = oms.create_orders(
        "portfolio",
        [{"security_id": "s1", "side": "SELL", "quantity": 200}],
        actor="operator",
    )[0]
    oms.transition(order_id, "APPROVED", actor="reviewer")
    oms.transition(order_id, "SUBMITTED", actor="operator")
    filled = oms.transition(order_id, "FILLED", actor="simulator")

    assert filled["version"] == 4
    assert filled["status"] == "FILLED"
