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
slow = 15
atr_mult_sl = 1.0
atr_mult_tp = 4.0
contract_size = 100
daily_max_loss = 500  # 每日最大虧損設定
test = False


def move_sl_to_breakeven(position):
        try:
            current_price = mt5.symbol_info_tick(symbol).last
            entry_price = position.price_open
            current_sl = position.sl
            current_tp = position.tp
            
            # 計算半個TP距離
            if position.type == mt5.POSITION_TYPE_BUY:
                half_tp_price = entry_price + (current_tp - entry_price) / 2
                # 如果當前價格達到半個TP，且還沒移動到breakeven
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


def get_today_pnl():
    """
    使用 MT5 服務器時間計算今日損益
    """
    try:
        # 獲取 MT5 服務器當前時間
        server_info = mt5.terminal_info()
        if server_info is None:
            return 0
            
        # 使用 UTC 時間
        utc_now = datetime.now(timezone.utc)
        utc_today_start = utc_now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # 1. 今日已平倉損益
        deals = mt5.history_deals_get(utc_today_start, utc_now)
        realized_pnl = 0
        if deals:
            for deal in deals:
                if deal.symbol == symbol and deal.type in [mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL]:
                    realized_pnl += deal.profit

        # 2. 當前持倉浮動損益
        positions = mt5.positions_get(symbol=symbol)
        unrealized_pnl = 0
        if positions:
            for pos in positions:
                # 檢查是否為今日開倉
                pos_time_utc = datetime.fromtimestamp(pos.time, tz=timezone.utc)
                if pos_time_utc >= utc_today_start:
                    unrealized_pnl += pos.profit

        return realized_pnl + unrealized_pnl
        
    except Exception as e:
        print(f"計算PnL失敗: {e}")
        return 0
        


class TradingBotUI:
    def __init__(self, root):
        self.root = root
        self.root.title("StrategyBasedBOT 狀態面板")
        self.status_text = tk.StringVar()
        self.pnl_text = tk.StringVar()
        self.holding_text = tk.StringVar()
        self.signal_text = tk.StringVar()
        self.balance_text = tk.StringVar()
        self.time_now_text = tk.StringVar()
        self.last_time_update_text = tk.StringVar()

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
        self.time_now_label = tk.Label(root, textvariable=self.time_now_text, font=("Arial", 12))
        self.time_now_label.pack(pady=5)
        self.last_time_update_label = tk.Label(root, textvariable=self.last_time_update_text, font=("Arial", 12))
        self.last_time_update_label.pack(pady=5)
        self.status_text.set("初始化中...")

    def update(self, status, pnl, balance, holding, signal,time_now, last_time_update):
        self.status_text.set(status)
        self.pnl_text.set(f"今日損益: {pnl:.2f}")
        self.balance_text.set(f"帳戶餘額: {balance:.2f}")
        self.holding_text.set(f"當前持倉: {holding}")
        self.signal_text.set(f"最新信號: {signal}")
        self.time_now_text.set(f"當前時間: {time_now}")
        self.last_time_update_text.set(f"最後更新時間: {last_time_update}")

    
def trading_loop(ui: TradingBotUI, trading_company, percentage_of_risk=0.01, daily_max_loss_percentage=0.05):
    status = ""
    signal = "None"
    balance = 0

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
        # 風控
        today_pnl = get_today_pnl()

        ui.update(status, today_pnl, balance, currentHolding, signal,datetime.now().strftime("%H:%M:%S"), "")
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
                move_sl_to_breakeven(positions[0])
            else:
                currentHolding = "None"

            daily_max_profit_dynamic = balance * daily_max_loss_percentage

            if today_pnl >= daily_max_profit_dynamic:
                status = "已達日內最大獲利，暫停交易"
                ui.update(status, today_pnl, balance, currentHolding, signal,datetime.now().strftime("%H:%M:%S"), datetime.now().strftime("%H:%M:%S"))
                time.sleep(60)
                continue
            if today_pnl <= -daily_max_loss:
                status = "已達日內最大虧損，暫停交易"
                ui.update(status, today_pnl, balance, currentHolding, signal,datetime.now().strftime("%H:%M:%S"), datetime.now().strftime("%H:%M:%S"))
                time.sleep(60)
                continue

            # 取得最新K線資料
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 0, 100)
            if rates is None or len(rates) < slow + 1:
                status = "K線資料不足，等待中"
                ui.update(status, today_pnl, balance, currentHolding, signal,datetime.now().strftime("%H:%M:%S"), datetime.now().strftime("%H:%M:%S"))
                time.sleep(1)
                continue

            close_prices = [bar['close'] for bar in rates]
            ema_fast = calculate_ema(close_prices, fast)
            ema_slow = calculate_ema(close_prices, slow)
            atr = calculate_atr([{'high': bar['high'], 'low': bar['low'], 'close': bar['close']} for bar in rates], 14)
            
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
            else:
                status = "等待交易訊號"

            ui.update(status, today_pnl, balance, currentHolding, signal,datetime.now().strftime("%H:%M:%S"), datetime.now().strftime("%H:%M:%S"))

        time.sleep(1)

def run_account():
    percentage_of_risk = float(input("設定每單最大虧損:(E.g 0.01 = 1% , 0.1 = 10%...ETC)\n"))
    trading_company = input("請輸入交易公司:\n")
    daily_max_loss_percentage = float(input("設定每日最大虧損百分比:(E.g 0.05 = 5% , 0.1 = 10%...ETC)\n"))
    root = tk.Tk()
    ui = TradingBotUI(root)
    t = Thread(target=trading_loop, args=(ui, trading_company, percentage_of_risk,daily_max_loss_percentage), daemon=True)
    t.start()
    root.mainloop()

if __name__ == "__main__":
    run_account()