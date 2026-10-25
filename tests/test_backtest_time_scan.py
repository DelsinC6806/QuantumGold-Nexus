import importlib.util
from datetime import datetime
from pathlib import Path


def load_backtest_module():
    module_path = Path(__file__).resolve().parents[1] / "src" / "backtest" / "backtest_time_based_vp.py"
    spec = importlib.util.spec_from_file_location("backtest_time_based_vp", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scan_time_matches_8pm_to_11pm_every_15_minutes():
    module = load_backtest_module()

    assert module.current_ts_is_scan_time(datetime(2024, 1, 1, 20, 0), 20, 23, 15)
    assert module.current_ts_is_scan_time(datetime(2024, 1, 1, 20, 15), 20, 23, 15)
    assert module.current_ts_is_scan_time(datetime(2024, 1, 1, 20, 45), 20, 23, 15)
    assert module.current_ts_is_scan_time(datetime(2024, 1, 1, 21, 30), 20, 23, 15)
    assert module.current_ts_is_scan_time(datetime(2024, 1, 1, 23, 0), 20, 23, 15)

    assert not module.current_ts_is_scan_time(datetime(2024, 1, 1, 19, 59), 20, 23, 15)
    assert not module.current_ts_is_scan_time(datetime(2024, 1, 1, 23, 15), 20, 23, 15)
    assert not module.current_ts_is_scan_time(datetime(2024, 1, 1, 20, 5), 20, 23, 15)
