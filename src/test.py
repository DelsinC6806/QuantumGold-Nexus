import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta
symbol = "XAUUSD"
position = mt5.positions_get(symbol=symbol)
type = "buy"
try:
        current_price = 1
        entry_price = 12
        current_sl = 10
        current_tp = 16
        half_tp_price = entry_price + (current_tp - entry_price) / 2
        print(half_tp_price)
        
except Exception as e:
        print(f"計算PnL失敗: {e}")
        print(0)