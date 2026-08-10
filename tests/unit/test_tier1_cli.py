import sys
from pathlib import Path

import pandas as pd
import pytest

from main import _load_universe_file, _normalize_symbol, build_parser
from main import main as cli_main


@pytest.mark.parametrize(
    "raw,expected",
    [("1", "000001"), ("000001.SZ", "000001"), ("SH600000", "600000")],
)
def test_normalize_symbol_accepts_common_formats(raw, expected):
    assert _normalize_symbol(raw) == expected


@pytest.mark.parametrize("raw", ["", "ABC", "0000012", "nan"])
def test_normalize_symbol_rejects_invalid_values(raw):
    with pytest.raises(ValueError):
        _normalize_symbol(raw)


def test_universe_file_deduplicates_symbols(tmp_path: Path):
    path = tmp_path / "universe.csv"
    pd.DataFrame(
        {"symbol": ["000001", "000001.SZ", "920001"], "name": ["A", "A2", "B"]}
    ).to_csv(path, index=False)
    items = _load_universe_file(str(path))
    assert [item.symbol for item in items] == ["000001", "920001"]
    assert [item.exchange for item in items] == ["SZ", "BJ"]


def test_help_exposes_formal_workflow_but_not_retired_scan():
    help_text = build_parser().format_help()
    assert "workflow" in help_text
    assert "legacy-scan" in help_text
    assert "{screen-tier1" in help_text
    assert ",scan," not in help_text


def test_retired_scan_fails_before_legacy_initialization(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py", "scan"])
    with pytest.raises(SystemExit) as exc:
        cli_main()
    assert exc.value.code == 2
    assert "已停用的旧入口" in capsys.readouterr().err


def test_legacy_scan_requires_explicit_confirmation(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py", "legacy-scan"])
    with pytest.raises(SystemExit) as exc:
        cli_main()
    assert exc.value.code == 2
    assert "必须提供--i-understand" in capsys.readouterr().err
