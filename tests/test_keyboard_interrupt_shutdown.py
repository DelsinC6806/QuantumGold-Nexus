import importlib
import sys
import types
from pathlib import Path


def load_module(monkeypatch):
    fake_mt5 = types.ModuleType("MetaTrader5")
    fake_mt5.initialize = lambda *args, **kwargs: True
    fake_mt5.shutdown = lambda: None
    fake_mt5.DEAL_TYPE_SELL = 0
    fake_mt5.DEAL_REASON_SL = 0
    fake_mt5.DEAL_REASON_TP = 0
    fake_mt5.POSITION_TYPE_BUY = 0
    fake_mt5.POSITION_TYPE_SELL = 1
    fake_mt5.TIMEFRAME_M15 = 0
    fake_mt5.history_deals_get = lambda *args, **kwargs: []
    fake_mt5.positions_get = lambda *args, **kwargs: []
    fake_mt5.symbol_info_tick = lambda *args, **kwargs: None
    fake_mt5.symbol_info = lambda *args, **kwargs: None
    fake_mt5.account_info = lambda *args, **kwargs: None
    monkeypatch.setitem(sys.modules, "MetaTrader5", fake_mt5)

    src_dir = Path(__file__).resolve().parents[1] / "src"
    monkeypatch.syspath_prepend(str(src_dir))

    sys.modules.pop("kalmans_filter_time_based_nas100", None)
    return importlib.import_module("kalmans_filter_time_based_nas100")


def test_main_handles_keyboard_interrupt(monkeypatch, capsys):
    module = load_module(monkeypatch)

    def raise_keyboard_interrupt(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(module, "trading_loop", raise_keyboard_interrupt)
    monkeypatch.setattr(module, "send_discord_notification", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.mt5, "shutdown", lambda: None)

    module.main()

    captured = capsys.readouterr()
    assert "shutdown" in captured.out.lower()
