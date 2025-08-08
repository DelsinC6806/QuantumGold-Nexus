import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta
import time
import numpy as np
from strategy import calculate_ema, calculate_atr
from placetrade import place_trade
import tkinter as tk
from threading import Thread
from multiprocessing import Process

symbol = "XAUUSD.x"
fast = 5
slow = 20
atr_mult_sl = 1.0
atr_mult_tp = 3.5
contract_size = 100

def get_current_holding():
    """
    獲取當前持倉狀態
    """
    positions = mt5.positions_get(symbol=symbol)
    if positions and len(positions) > 0:
        pos_type = positions[0].type
        if pos_type == mt5.POSITION_TYPE_BUY:
            return "BUY"
        elif pos_type == mt5.POSITION_TYPE_SELL:
            return "SELL"

    return "None"

class TradingBotUI:
    def __init__(self, root):
        self.root = root
        self.root.title("StrategyBasedBOT 狀態面板")
        self.status_text = tk.StringVar()
        self.holding_text = tk.StringVar()
        self.balance_text = tk.StringVar()
        self.time_now_text = tk.StringVar()
        self.last_time_update_text = tk.StringVar()
        self.trade_count_text = tk.StringVar()

        self.status_label = tk.Label(root, textvariable=self.status_text, font=("Arial", 12), fg="blue")
        self.status_label.pack(pady=5)
        self.balance_label = tk.Label(root, textvariable=self.balance_text, font=("Arial", 12))
        self.balance_label.pack(pady=5)
        self.holding_label = tk.Label(root, textvariable=self.holding_text, font=("Arial", 12))
        self.holding_label.pack(pady=5)
        self.time_now_label = tk.Label(root, textvariable=self.time_now_text, font=("Arial", 12))
        self.time_now_label.pack(pady=5)
        self.last_time_update_label = tk.Label(root, textvariable=self.last_time_update_text, font=("Arial", 12))
        self.last_time_update_label.pack(pady=5)
        self.trade_count_label = tk.Label(root, textvariable=self.trade_count_text, font=("Arial", 12))
        self.trade_count_label.pack(pady=5)
        self.status_text.set("初始化中...")

    def update(self, status, balance, holding,time_now, last_time_update,trade_count=0):
        self.status_text.set(status)
        self.balance_text.set(f"帳戶餘額: {balance:.2f}")
        self.holding_text.set(f"當前持倉: {holding}")
        self.time_now_text.set(f"伺服器時間: {time_now}")
        self.last_time_update_text.set(f"最後更新時間: {last_time_update}")
        self.trade_count_text.set(f"交易次數: {trade_count}")

def trading_loop(ui: TradingBotUI, trading_company, percentage_of_risk=0.01): 
    if not mt5.initialize():
        ui.update("MetaTrader 5 初始化失敗", 0, 0, "None", "None")
        return
    account_info = mt5.account_info()
    status = ""
    balance = account_info.balance if account_info else 0
    trade_count = len(mt5.history_orders_get(datetime.now() - timedelta(days=1), datetime.now(), symbol=symbol))
    position = get_current_holding()
    last_time_update = datetime.now().strftime("%H:%M:%S")
    signal = 0
    ui.update(status, balance, position, datetime.now().strftime("%H:%M:%S"), last_time_update,trade_count)

    while True:

        now = datetime.now()
        ui.update(status, balance, position, now, last_time_update,trade_count)
        if now.hour == 6 and now.minute == 0:
            # 每天早上6點重置交易次數
            trade_count = 0
            ui.update("已重置交易次數", balance, position, now, last_time_update,trade_count)

        if now.minute % 15 == 0 and (now.second == 0 or now.second == 1 or now.second == 2):
            signal = 0
            account_info = mt5.account_info()
            if account_info is None:
                ui.update("取得帳戶資訊失敗", 0, 0, position, "None")
                time.sleep(1)
                continue
            if account_info.trade_allowed == False:
                ui.update("交易未啟用", 0, 0, "None", "None")
                continue

            # 15 minutes checking
            last_time_update=datetime.now().strftime("%H:%M:%S")
            balance = account_info.balance  
            position = get_current_holding()


            # 取得最新K線資料
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 30)
            if rates is None or len(rates) < 30:
                status = "無法獲取K線資料，請檢查網絡連接或交易品種"
                ui.update(status, balance, position, now, last_time_update,trade_count)
                time.sleep(1)
                continue
            close_prices = [bar['close'] for bar in rates]
            
            ema_fast = calculate_ema(close_prices, fast)
            ema_slow = calculate_ema(close_prices, slow)
            atr = calculate_atr([{'high': bar['high'], 'low': bar['low'], 'close': bar['close']} for bar in rates], 14)
            
            if trade_count >= 1:
                status = "已達日內最大交易數，暫停交易"
                ui.update(status, balance, position, now, last_time_update,trade_count)
                continue

            # Volatility filter
            if np.isnan(atr[-1]) or atr[-1] < np.nanmedian(atr[max(0, len(atr)-250):]):
                status = "波動率過低，等待確認"
                ui.update(status, balance, position, now, last_time_update,trade_count)
                continue
                    
            if ema_fast[-2] < ema_slow[-2] and ema_fast[-1] > ema_slow[-1]:
                signal = 1  # 多
            elif ema_fast[-2] > ema_slow[-2] and ema_fast[-1] < ema_slow[-1]:
                signal = -1 # 空
            else:
                signal = 0

            # 訊號偵測
            if signal == 1 and position == "None":
                # BUY 訊號
                entry_price = close_prices[-1]
                sl = entry_price - atr_mult_sl * atr[-1]
                tp = entry_price + atr_mult_tp * atr[-1]
                sl_distance = abs(entry_price - sl)
                risk_per_trade = balance * percentage_of_risk
                lot = round(risk_per_trade / (sl_distance * contract_size), 2)
                status = f"下單 BUY: lot={lot:.2f}, sl={sl:.2f}, tp={tp:.2f}, 時間={now.strftime('%H:%M:%S')}"
                place_trade(symbol, "BUY", lot, sl, tp, entry_price, trading_company)
                position = "BUY"
                trade_count += 1
            elif signal == -1 and position == "None":
                # SELL 訊號
                entry_price = close_prices[-1]
                sl = entry_price + atr_mult_sl * atr[-1]
                tp = entry_price - atr_mult_tp * atr[-1]
                sl_distance = abs(sl - entry_price)
                risk_per_trade = balance * percentage_of_risk
                lot = round(risk_per_trade / (sl_distance * contract_size), 2)
                status = f"下單 SELL: lot={lot:.2f}, sl={sl:.2f}, tp={tp:.2f}, 時間={now.strftime('%H:%M:%S')}"
                place_trade(symbol, "SELL", lot, sl, tp, entry_price, trading_company)
                position = "SELL"
                trade_count += 1

            if position != "None":
                status = f"持有 {position} 位置，交易次數: {trade_count}"
                #收盤前平倉
                if now.hour == 4 and now.minute == 30:
                    if position == "BUY":
                        place_trade(symbol, "SELL", lot, sl, tp, entry_price, trading_company)
                    elif position == "SELL":
                        place_trade(symbol, "BUY", lot, sl, tp, entry_price, trading_company)
                    position = "None"
                    status += "，已平倉"

            ui.update(status, balance, position, now, last_time_update,trade_count)

        time.sleep(1)

def run_account():
    percentage_of_risk = 0.005
    trading_company = 'OANDA'
    root = tk.Tk()
    ui = TradingBotUI(root)
    t = Thread(target=trading_loop, args=(ui, trading_company, percentage_of_risk), daemon=True)
    t.start()
    root.mainloop()

if __name__ == "__main__":
    run_account()