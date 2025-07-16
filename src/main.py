import MetaTrader5 as mt5
from datetime import datetime
import time
import numpy as np
from strategy import calculate_ema, calculate_atr
from placetrade import place_trade
import tkinter as tk
from threading import Thread
from multiprocessing import Process

symbol = "XAUUSD"
fast = 5
slow = 15
atr_mult_sl = 1.0
atr_mult_tp = 4.0
contract_size = 100
daily_max_loss = 500  # 每日最大虧損設定
test = False
def get_today_pnl():
    # 你可根據 trade_log.txt 或 MT5 歷史訂單計算今日已實現損益
    return 0  # 這裡請自行實作

class TradingBotUI:
    def __init__(self, root):
        self.root = root
        self.root.title("StrategyBasedBOT 狀態面板")
        self.status_text = tk.StringVar()
        self.pnl_text = tk.StringVar()
        self.holding_text = tk.StringVar()
        self.signal_text = tk.StringVar()
        self.balance_text = tk.StringVar()
        self.status_label = tk.Label(root, textvariable=self.status_text, font=("Arial", 12), fg="blue")
        self.status_label.pack(pady=5)
        self.pnl_label = tk.Label(root, textvariable=self.pnl_text, font=("Arial", 12))
        self.pnl_label.pack(pady=5)
        self.balance_label = tk.Label(root, textvariable=self.balance_text, font=("Arial", 12))
        self.balance_label.pack(pady=5)
        self.holding_label = tk.Label(root, textvariable=self.holding_text, font=("Arial", 12))
        self.holding_label.pack(pady=5)
        self.signal_label = tk.Label(root, textvariable=self.signal_text, font=("Arial", 12))
        self.signal_label.pack(pady=5)
        self.status_text.set("初始化中...")

    def update(self, status, pnl, balance, holding, signal):
        self.status_text.set(status)
        self.pnl_text.set(f"今日損益: {pnl:.2f}")
        self.balance_text.set(f"帳戶餘額: {balance:.2f}")
        self.holding_text.set(f"當前持倉: {holding}")
        self.signal_text.set(f"最新信號: {signal}")

def trading_loop(ui: TradingBotUI, trading_company, percentage_of_risk=0.01):
    if not mt5.initialize():
        ui.update("MetaTrader 5 初始化失敗", 0, 0, "None", "None")
        return

    currentHolding = None
    if(test):
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 100)
        close_prices = [bar['close'] for bar in rates]
        entry_price = close_prices[-1]
        place_trade(symbol, "BUY", 0.01, entry_price-10, entry_price+10, entry_price,trading_company)  # 測試下單
        return

    while True:
        now = datetime.now()
        if now.minute % 15 == 0 and now.second == 0:
            account_info = mt5.account_info()
            if account_info is None:
                ui.update("取得帳戶資訊失敗", 0, 0, currentHolding, "None")
                time.sleep(1)
                continue
            balance = account_info.balance
            positions = mt5.positions_get(symbol=symbol)
            if positions and len(positions) > 0:
                pos_type = positions[0].type
                if pos_type == mt5.POSITION_TYPE_BUY:
                    currentHolding = "BUY"
                elif pos_type == mt5.POSITION_TYPE_SELL:
                    currentHolding = "SELL"
                else:
                    currentHolding = "None"
            else:
                currentHolding = "None"

            # 風控
            daily_max_profit_dynamic = balance * 0.05
            today_pnl = get_today_pnl()
            status = ""
            signal = "None"

            if today_pnl >= daily_max_profit_dynamic:
                status = "已達日內最大獲利，暫停交易"
                ui.update(status, today_pnl, balance, currentHolding, signal)
                time.sleep(60)
                continue
            if today_pnl <= -daily_max_loss:
                status = "已達日內最大虧損，暫停交易"
                ui.update(status, today_pnl, balance, currentHolding, signal)
                time.sleep(60)
                continue

            # 取得最新K線資料
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 100)
            if rates is None or len(rates) < slow + 1:
                status = "K線資料不足，等待中"
                ui.update(status, today_pnl, balance, currentHolding, signal)
                time.sleep(1)
                continue

            close_prices = [bar['close'] for bar in rates]
            ema_fast = calculate_ema(close_prices, fast)
            ema_slow = calculate_ema(close_prices, slow)
            atr = calculate_atr([{'high': bar['high'], 'low': bar['low'], 'close': bar['close']} for bar in rates], 14)
            
            # 訊號偵測
            if ema_fast[-2] < ema_slow[-2] and ema_fast[-1] > ema_slow[-1]:
                # BUY 訊號
                entry_price = close_prices[-1]
                sl = entry_price - atr_mult_sl * atr[-1]
                tp = entry_price + atr_mult_tp * atr[-1]
                sl_distance = abs(entry_price - sl)
                risk_per_trade = min(balance * percentage_of_risk, daily_max_loss)
                lot_size = risk_per_trade / (sl_distance * contract_size) if sl_distance > 0 else 0.01
                lot_size = max(0.01, round(lot_size, 2)) 
                status = f"下單 BUY: lot={lot_size:.2f}, sl={sl:.2f}, tp={tp:.2f}"
                signal = "BUY"
                place_trade(symbol, "BUY", lot_size, sl, tp, entry_price, trading_company)
                currentHolding = "BUY"
            elif ema_fast[-2] > ema_slow[-2] and ema_fast[-1] < ema_slow[-1]:
                # SELL 訊號
                entry_price = close_prices[-1]
                sl = entry_price + atr_mult_sl * atr[-1]
                tp = entry_price - atr_mult_tp * atr[-1]
                sl_distance = abs(sl - entry_price)
                risk_per_trade = min(balance * percentage_of_risk, daily_max_loss)
                lot_size = risk_per_trade / (sl_distance * contract_size) if sl_distance > 0 else 0.01
                lot_size = max(0.01, round(lot_size, 2)) 
                status = f"下單 SELL: lot={lot_size:.2f}, sl={sl:.2f}, tp={tp:.2f}"
                signal = "SELL"
                place_trade(symbol, "SELL", lot_size, sl, tp, entry_price, trading_company)
                currentHolding = "SELL"
            else:
                status = "等待交易訊號"

            ui.update(status, today_pnl, balance, currentHolding, signal)

        time.sleep(1)

def run_account():
    percentage_of_risk = float(input("設定每單最大虧損:(E.g 0.01 = 1% , 0.1 = 10%...ETC)\n"))
    trading_company = input("請輸入交易公司:\n")
    root = tk.Tk()
    ui = TradingBotUI(root)
    t = Thread(target=trading_loop, args=(ui, trading_company, percentage_of_risk), daemon=True)
    t.start()
    root.mainloop()

if __name__ == "__main__":
    run_account()