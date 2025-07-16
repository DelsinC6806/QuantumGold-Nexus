import unittest
from unittest.mock import patch, MagicMock
import src.main

class TestStrategyCases(unittest.TestCase):
    def setUp(self):
        self.ui = MagicMock()
        patcher_mt5 = patch('src.main.mt5')
        self.mock_mt5 = patcher_mt5.start()
        self.addCleanup(patcher_mt5.stop)
        patcher_ema = patch('src.main.calculate_ema')
        patcher_atr = patch('src.main.calculate_atr')
        self.mock_ema = patcher_ema.start()
        self.mock_atr = patcher_atr.start()
        self.addCleanup(patcher_ema.stop)
        self.addCleanup(patcher_atr.stop)
        patcher_place_trade = patch('src.main.place_trade')
        self.mock_place_trade = patcher_place_trade.start()
        self.addCleanup(patcher_place_trade.stop)
        patcher_close_position = patch('src.main.close_position')
        self.mock_close_position = patcher_close_position.start()
        self.addCleanup(patcher_close_position.stop)
        patcher_sleep = patch('src.main.time.sleep', return_value=None)
        patcher_sleep.start()
        self.addCleanup(patcher_sleep.stop)

    def test_no_position_buy_signal(self):
        self.mock_mt5.positions_get.return_value = None
        self.mock_mt5.account_info.return_value = MagicMock(balance=10000)
        self.mock_mt5.copy_rates_from_pos.return_value = [{'close': 10, 'high': 11, 'low': 9}]*100
        # 產生 BUY 訊號
        self.mock_ema.side_effect = lambda prices, window: [1]*98 + [5, 10] if window == src.main.fast else [1]*98 + [10, 5]
        self.mock_atr.return_value = [1]*100
        with patch('src.main.datetime') as mock_datetime:
            mock_datetime.now.return_value = src.main.datetime(2025, 7, 8, 15, 0, 0)
            src.main.trading_loop(self.ui, max_loops=1)
        self.mock_place_trade.assert_called_with(src.main.symbol, "BUY", unittest.mock.ANY, unittest.mock.ANY, unittest.mock.ANY, unittest.mock.ANY)

    def test_no_position_sell_signal(self):
        # 無持倉，出現SELL訊號
        self.mock_mt5.positions_get.return_value = None
        self.mock_mt5.account_info.return_value = MagicMock(balance=10000)
        self.mock_mt5.copy_rates_from_pos.return_value = [{'close': 10, 'high': 11, 'low': 9}]*100
        # 設定 EMA 交叉產生 SELL 訊號
        self.mock_ema.side_effect = lambda prices, window: [1]*98 + [10, 5] if window == src.main.fast else [1]*98 + [5, 10]
        with patch('src.main.datetime') as mock_datetime:
            mock_datetime.now.return_value = src.main.datetime(2025, 7, 8, 15, 0, 0)
            src.main.trading_loop(self.ui, max_loops=1)
        self.mock_place_trade.assert_called_with(src.main.symbol, "SELL", unittest.mock.ANY, unittest.mock.ANY, unittest.mock.ANY, unittest.mock.ANY)

    def test_buy_position_reverse_to_sell(self):
        # 持有BUY單，遇到SELL訊號，應先平倉再反手
        mock_position = MagicMock(type=0, volume=0.3, price_open=10)
        self.mock_mt5.positions_get.return_value = [mock_position]
        self.mock_mt5.account_info.return_value = MagicMock(balance=10000)
        self.mock_mt5.copy_rates_from_pos.return_value = [{'close': 10, 'high': 11, 'low': 9}]*100
        # 設定 EMA 交叉產生 SELL 訊號
        self.mock_ema.side_effect = lambda prices, window: [1]*98 + [10, 5] if window == src.main.fast else [1]*98 + [5, 10]
        with patch('src.main.datetime') as mock_datetime:
            mock_datetime.now.return_value = src.main.datetime(2025, 7, 8, 15, 0, 0)
            src.main.trading_loop(self.ui, max_loops=1)
        self.mock_close_position.assert_called_with(src.main.symbol, "BUY", 0.3)
        self.mock_place_trade.assert_called_with(src.main.symbol, "SELL", unittest.mock.ANY, unittest.mock.ANY, unittest.mock.ANY, unittest.mock.ANY)

    def test_sell_position_reverse_to_buy(self):
        # 持有SELL單，遇到BUY訊號，應先平倉再反手
        mock_position = MagicMock(type=1, volume=0.3, price_open=10)
        self.mock_mt5.positions_get.return_value = [mock_position]
        self.mock_mt5.account_info.return_value = MagicMock(balance=10000)
        self.mock_mt5.copy_rates_from_pos.return_value = [{'close': 10, 'high': 11, 'low': 9}]*100
        # 設定 EMA 交叉產生 BUY 訊號
        self.mock_ema.side_effect = lambda prices, window: [1]*98 + [5, 10] if window == src.main.fast else [1]*98 + [10, 5]
        with patch('src.main.datetime') as mock_datetime:
            mock_datetime.now.return_value = src.main.datetime(2025, 7, 8, 15, 0, 0)
            src.main.trading_loop(self.ui, max_loops=1)
        self.mock_close_position.assert_called_with(src.main.symbol, "SELL", 0.3)
        self.mock_place_trade.assert_called_with(src.main.symbol, "BUY", unittest.mock.ANY, unittest.mock.ANY, unittest.mock.ANY, unittest.mock.ANY)

    def test_day_stop(self):
        self.mock_mt5.positions_get.return_value = None
        self.mock_mt5.account_info.return_value = MagicMock(balance=10000)
        self.mock_mt5.copy_rates_from_pos.return_value = [{'close': 10, 'high': 11, 'low': 9}]*100
        # 直接讓 get_today_pnl_and_count 回傳超過最大獲利
        with patch('src.main.get_today_pnl_and_count', return_value=(10000, 10)):
            with patch('src.main.datetime') as mock_datetime:
                mock_datetime.now.return_value = src.main.datetime(2025, 7, 8, 15, 0, 0)
                src.main.trading_loop(self.ui, max_loops=1)
        self.ui.update.assert_any_call("已達日內最大獲利，暫停交易", 10000, 10000, unittest.mock.ANY, unittest.mock.ANY, 10)

if __name__ == '__main__':
    unittest.main()