import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta
import time
import numpy as np
from strategy import calculate_ema, calculate_atr
from placetrade import place_trade
import tkinter as tk
from threading import Thread
from multiprocessing import Process
import math
import os

symbol = "XAUUSD.r"
fast = 5
slow = 20
atr_mult_sl = 1.0
atr_mult_tp = 3.5
contract_size = 100

def count_trades_today_simple(log_path: str, target_date: str) -> int:
    """
    只要 trade_log.txt 裡有幾行包含今天日期（格式: YYYY-MM-DD）
    """
    if not os.path.isfile(log_path):
        return 0
    count = 0
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            if target_date in line:
                count += 1
    return count

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
        self.time_now_text.set(f"香港時間: {time_now}")
        self.last_time_update_text.set(f"最後更新時間: {last_time_update}")
        self.trade_count_text.set(f"交易次數: {trade_count}")

def round_to_step(volume, step):
    """依 symbol 的 volume_step 修正手數（向下取整避免被拒單）"""
    if step <= 0:
        return round(volume, 2)
    return math.floor(volume / step) * step

def close_all_positions(symbol, trading_company):
    """關閉該 symbol 的所有持倉"""
    positions = mt5.positions_get(symbol=symbol) or []
    tick = mt5.symbol_info_tick(symbol)
    for pos in positions:
        vol = pos.volume
        if vol <= 0:
            continue
        if pos.type == mt5.POSITION_TYPE_BUY:
            place_trade(symbol, "SELL", vol, 0, 0, tick.bid, trading_company)
        elif pos.type == mt5.POSITION_TYPE_SELL:
            place_trade(symbol, "BUY", vol, 0, 0, tick.ask, trading_company)

def trading_loop(ui: TradingBotUI, trading_company, percentage_of_risk=0.01): 
    if not mt5.initialize():
        ui.update("MetaTrader 5 初始化失敗", 0, 0, "None", "None")
        return
    account_info = mt5.account_info()
    status = ""
    balance = account_info.balance if account_info else 0
    position = get_current_holding()
    if datetime.now().hour >= 0 and datetime.now().hour < 6 :
        today = datetime.now() - timedelta(days=1)
    else:
        today = datetime.now()
    today = today.strftime("%Y-%m-%d")
    trade_count = count_trades_today_simple("trade_log.txt", today)
    last_time_update = datetime.now().strftime("%H:%M:%S")
    signal = 0
    last_bar_time = None  # 新K棒保護
    sym_info = mt5.symbol_info(symbol)
    vol_step = sym_info.volume_step if sym_info else 0.01
    ui.update(status, balance, position, datetime.now().strftime("%H:%M:%S"), last_time_update,trade_count)

    while True:

        now = datetime.now()
        ui.update(status, balance, position, now, last_time_update, trade_count)

        # 每天早上6點重置交易次數（香港時間）
        if now.hour == 6 and now.minute == 0:
            trade_count = 0
            ui.update("已重置交易次數", balance, position, now, last_time_update,trade_count)

        # 收盤前強制平倉：香港時間 04:45
        if now.hour == 4 and now.minute == 45 and position != "None":
            close_all_positions(symbol, trading_company)
            position = "None"
            status = "香港時間 04:45 強制平倉"
            ui.update(status, balance, position, now, last_time_update, trade_count)
            time.sleep(60)
            continue

        if now.minute % 15 == 0 and (now.second in (0, 1, 2)):
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
            last_time_update = now.strftime("%H:%M:%S")
            balance = account_info.balance  
            position = get_current_holding()

            # 取得更多K線資料（用於ATR過濾至少250根）
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 300)
            if rates is None or len(rates) < 30:
                status = "無法獲取K線資料，請檢查網絡連接或交易品種"
                ui.update(status, balance, position, now, last_time_update,trade_count)
                time.sleep(1)
                continue

            # 新K棒保護：同一根K棒只處理一次
            latest_bar_ts = int(rates[-1]['time'])
            if last_bar_time == latest_bar_ts:
                print(f"已處理過最新K棒，跳過 {latest_bar_ts}")
                time.sleep(1)
                continue
            last_bar_time = latest_bar_ts

            close_prices = [bar['close'] for bar in rates]
            ema_fast = calculate_ema(close_prices, fast)
            ema_slow = calculate_ema(close_prices, slow)
            atr = calculate_atr([{'high': bar['high'], 'low': bar['low'], 'close': bar['close']} for bar in rates], 14)

            if trade_count >= 1:
                print("已達日內最大交易數，暫停交易")
                continue

            # Volatility filter（使用近250根的中位數）
            if np.isnan(atr[-1]) or atr[-1] < np.nanmedian(atr[-250:]):
                status = "波動率過低，等待確認"
                print(f"[{now:%Y-%m-%d %H:%M:%S}] ATR14<{atr[-1]:.2f}>  ATR250-med<{np.nanmedian(atr[-250:]):.2f}>")
                ui.update(status, balance, position, now, last_time_update, trade_count)
                continue
            else:
                status = "波動率正常，準備下單"
                print(f"[{now:%Y-%m-%d %H:%M:%S}] ATR14<{atr[-1]:.2f}>  ATR250-med<{np.nanmedian(atr[-250:]):.2f}>")
                ui.update(status, balance, position, now, last_time_update, trade_count)

            if ema_fast[-2] < ema_slow[-2] and ema_fast[-1] > ema_slow[-1]:
                signal = 1  # 多
            elif ema_fast[-2] > ema_slow[-2] and ema_fast[-1] < ema_slow[-1]:
                signal = -1 # 空
            else:
                signal = 0

            # 訊號偵測
            if signal == 1 and position == "None":
                entry_price = close_prices[-1]
                sl = entry_price - atr_mult_sl * atr[-1]
                tp = entry_price + atr_mult_tp * atr[-1]
                sl_distance = abs(entry_price - sl)
                risk_per_trade = balance * percentage_of_risk
                lot_raw = risk_per_trade / (sl_distance * contract_size)
                lot = round_to_step(lot_raw, vol_step)
                status = f"下單 BUY: lot={lot:.2f}, sl={sl:.2f}, tp={tp:.2f}, 時間={now}"
                place_trade(symbol, "BUY", lot, sl, tp, entry_price, trading_company)
                position = "BUY"
                trade_count += 1

            elif signal == -1 and position == "None":
                entry_price = close_prices[-1]
                sl = entry_price + atr_mult_sl * atr[-1]
                tp = entry_price - atr_mult_tp * atr[-1]
                sl_distance = abs(sl - entry_price)
                risk_per_trade = balance * percentage_of_risk
                lot_raw = risk_per_trade / (sl_distance * contract_size)
                lot = round_to_step(lot_raw, vol_step)
                status = f"下單 SELL: lot={lot:.2f}, sl={sl:.2f}, tp={tp:.2f}, 時間={now}"
                place_trade(symbol, "SELL", lot, sl, tp, entry_price, trading_company)
                position = "SELL"
                trade_count += 1

            ui.update(status, balance, position, now, last_time_update, trade_count)

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