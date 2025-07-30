import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta
import time
import numpy as np
from strategy import calculate_ema, calculate_atr
from placetrade import place_trade
import tkinter as tk
from threading import Thread
from multiprocessing import Process

symbol = "XAUUSD"
fast = 5
slow = 20
atr_mult_sl = 1.2
atr_mult_tp = 1.5
contract_size = 100
daily_max_loss = 500  # 每日最大虧損設定

test = False


def move_sl_to_breakeven(position):
        try:
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 100)
            close_prices = [bar['close'] for bar in rates]
            current_price = close_prices[-1]
            entry_price = position.price_open
            current_sl = position.sl
            current_tp = position.tp
            print('當前價格:', current_price, '入場價:', entry_price, '當前止損:', current_sl, '當前止盈:', current_tp)
            # 計算半個TP距離
            if position.type == mt5.POSITION_TYPE_BUY:
                half_tp_price = entry_price + (current_tp - entry_price) / 2
                # 如果當前價格達到半個TP，且還沒移動到breakeven
                print(f"BUY條件檢查: 當前價格={current_price:.2f}, 半TP價格={half_tp_price:.2f}, 入場價={entry_price:.2f}, 當前止損={current_sl:.2f}")
                if current_price >= half_tp_price and current_sl < entry_price:

                    modify_request = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "symbol": symbol,
                        "position": position.ticket,
                        "sl": entry_price,  # 移動到breakeven
                        "tp": current_tp,
                    }
                    result = mt5.order_send(modify_request)
                    if result.retcode == mt5.TRADE_RETCODE_DONE:
                        print(f"BUY止損已移動到breakeven: {entry_price}")
                        return True
            elif position.type == mt5.POSITION_TYPE_SELL:
                    half_tp_price = entry_price - (entry_price - current_tp) / 2
                    # 如果當前價格達到半個TP，且還沒移動到breakeven
                    print(f"SELL條件檢查: 當前價格={current_price:.2f}, 半TP價格={half_tp_price:.2f}, TP價格={position.tp}, 入場價={entry_price:.2f}, 當前止損={current_sl:.2f}")
                    if current_price <= half_tp_price and current_sl > entry_price:

                        modify_request = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "symbol": symbol,
                            "position": position.ticket,
                            "sl": entry_price,  # 移動到breakeven
                            "tp": current_tp,
                        }
                        result = mt5.order_send(modify_request)
                        if result.retcode == mt5.TRADE_RETCODE_DONE:
                            print(f"SELL止損已移動到breakeven: {entry_price}")
                            return True
                        
        except Exception as e:
            print(f"移動止損失敗: {e}")
        return False
    
def get_current_holding():
    """
    獲取當前持倉狀態
    """
    positions = mt5.positions_get(symbol=symbol)
    if positions and len(positions) > 0:
        pos_type = positions[0].type
        move_sl_to_breakeven(positions[0])
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
        self.time_now_text.set(f"當前時間: {time_now}")
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
    currentHolding = get_current_holding()
    last_time_update = datetime.now().strftime("%H:%M:%S")
    ui.update(status, balance, currentHolding, datetime.now().strftime("%H:%M:%S"), last_time_update,trade_count)

    while True:
        now = datetime.now()
        # 風控
        ui.update(status, balance, currentHolding, datetime.now().strftime("%H:%M:%S"), last_time_update,trade_count)
        #if now.minute % 1 == 0:
        if now.minute % 15 == 0 and (now.second == 0 or now.second == 1 or now.second == 2):
            account_info = mt5.account_info()
            if account_info is None:
                ui.update("取得帳戶資訊失敗", 0, 0, currentHolding, "None")
                time.sleep(1)
                continue
            if account_info.trade_allowed == False:
                ui.update("交易未啟用", 0, 0, "None", "None")
                continue

            # 15 minutes checking
            last_time_update=datetime.now().strftime("%H:%M:%S")
            balance = account_info.balance  
            currentHolding = get_current_holding()

            if trade_count >= 2:
                status = "已達日內最大交易數，暫停交易"
                ui.update(status, balance, currentHolding, datetime.
                          now().strftime("%H:%M:%S"), last_time_update,trade_count)
                time.sleep(60)
                continue

            # 取得最新K線資料
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 100)
            if rates is None or len(rates) < slow + 1:
                status = "K線資料不足，等待中"
                ui.update(status, balance, currentHolding, datetime.
                          now().strftime("%H:%M:%S"), last_time_update,trade_count)
                time.sleep(1)
                continue

            close_prices = [bar['close'] for bar in rates]
            ema_fast = calculate_ema(close_prices, fast)
            ema_slow = calculate_ema(close_prices, slow)
            atr = calculate_atr([{'high': bar['high'], 'low': bar['low'], 'close': bar['close']} for bar in rates], 14)
            
            # Volatility filter
            if np.isnan(atr[-1]) or atr[-1] < np.nanmedian(atr[max(0, -100):]):
                continue

            # 訊號偵測
            if ema_fast[-2] < ema_slow[-2] and ema_fast[-1] > ema_slow[-1] and currentHolding == "None":
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
                trade_count += 1
            elif ema_fast[-2] > ema_slow[-2] and ema_fast[-1] < ema_slow[-1] and currentHolding == "None":
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
                trade_count += 1
            else:
                status = "等待交易訊號"

            ui.update(status, balance, currentHolding, datetime.now().strftime("%H:%M:%S"), last_time_update,trade_count)

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