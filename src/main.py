import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta
import time
import numpy as np
from strategy import calculate_ema, calculate_atr, calculate_rsi
from placetrade import place_trade
from threading import Thread
from multiprocessing import Process
import math
import os

fast = 5
slow = 20
atr_mult_sl = 1.0
atr_mult_tp = 2.8   #lower 3.5 to 3.0 for better result
contract_size = 100
symbol = ""
position = "None"
instances = [
    {                                                                       
        'mt5_path': 'C:/Program Files/MetaTrader 5/terminal64.exe',
        'instance_name': 'Fxify 25000',
        'symbol': ['USDJPY.r','GBPUSD.r','EURUSD.r'],
        'trading_company': 'OANDA',
        'percentage_of_risk': 0.005,
        'position_holding': "None"
    },
    {
        "mt5_path": 'C:/Program Files/MetaTrader 5 - 3/terminal64.exe',
        "instance_name": 'OANDA 10000',
        "symbol": "XAUUSD",
        "trading_company": "OANDA",
        "percentage_of_risk": 0.005,
        'position_holding': "None"
    },
    # Add more instances as needed
]

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
    
def trading_loop_master_slave(instances):

    master = instances[0]
    slaves = instances[1:]

    if not mt5.initialize(path=master['mt5_path']):
            print(f"initialize() failed for {master['symbol']}, {master['instance_name']}")
            return
    
    account_info = mt5.account_info()
    position = get_current_holding()

    if datetime.now().hour >= 0 and datetime.now().hour < 6 :
        today = datetime.now() - timedelta(days=1)
    else:
        today = datetime.now()

    today = today.strftime("%Y-%m-%d")
    trade_count = count_trades_today_simple("trade_log.txt", today)
    signal = 0
    last_bar_time = None  # 新K棒保護

    #loop start
    while True:
        now = datetime.now()

        #15 minutes loop start
        if now.minute % 15 == 0 and (now.second in (0, 1, 2)):
            if not mt5.initialize(path=master['mt5_path']):
                print(f"Re-initializing MT5 failed for {master['symbol']}, {master['instance_name']}")
                time.sleep(2)
                continue
            account_info = mt5.account_info()
            if account_info is None:
                print("取得帳戶資訊失敗")
                time.sleep(1)
                continue

            # reset trade count at 6:00 am
            if now.hour == 6 and now.minute == 0:
                trade_count = 0

            # close all position at 4:45 am
            if now.hour == 4 and now.minute == 45 and position != "None":
                close_all_positions(master['symbol'], master['trading_company'])
                position = "None"
                time.sleep(60)
                continue

            #check trade count 
            if trade_count >= 3:
                print(f"{master['instance_name']}: 已達日內最大交易數，暫停交易")
                continue

            
            #session filter
            if not (7 <= now.hour < 23):
                print(f"not 7-23")
                continue    

            # 15 minutes checking
            position = get_current_holding()

            #Strategy start here

            #get h1 data (200 bar)
            for symbol in master['symbol']:
                rates_h1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 1, 200)
                close_h1 = [bar['close'] for bar in rates_h1]
                h1_ema50 = calculate_ema(close_h1, 50)[-1]
                h1_ema200 = calculate_ema(close_h1, 200)[-1]

                #bullish bearish checking on h1
                is_h1_bullish = h1_ema50 > h1_ema200
                is_h1_bearish = h1_ema50 < h1_ema200


                # get 250 bars of m15 data
                rates_m15 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 1, 250)
                close_m15 = [bar['close'] for bar in rates_m15]
                low_m15 = [bar['low'] for bar in rates_m15]
                high_m15 = [bar['high'] for bar in rates_m15]

                m15_ema50 = calculate_ema(close_m15, 50)
                m15_ema200 = calculate_ema(close_m15, 200)
                rsi = calculate_rsi(close_m15, 14)
                rsi_slope = rsi[-1] - rsi[-2]

                signal = 0
                curr_low = low_m15[-1]
                curr_high = high_m15[-1]
                curr_close = close_m15[-1]
                curr_ema50 = m15_ema50[-1]
                curr_rsi = rsi[-1]

                atr14_series = calculate_atr(rates_m15, 14)
                atr250_series = calculate_atr(rates_m15, 250)
                atr14_slope = atr14_series[-1] - atr14_series[-2]
                is_volatility_rising = atr14_slope > 0

                print(f"{master['instance_name']} [{symbol}] :[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]")
                print(f"H1 EMA 50:{h1_ema50:.2f}, H1 EMA 200: {h1_ema200:.2f}")
                print(f"M15 EMA 50: {m15_ema50[-1]:.2f}, M15 EMA 200: {m15_ema200[-1]:.2f}")

                # 【多頭入場】
                # A. 大勢: H1 EMA50 > EMA200
                # B. 回測: M15 Low 觸碰 EMA50 且 Close 收回上方
                # C. 動能: RSI 在 45-60 
                if is_h1_bullish and (m15_ema50[-1] > m15_ema200[-1]):
                    if curr_low <= curr_ema50 and curr_close > curr_ema50:
                        if (45 < curr_rsi < 60):
                            signal = 1
                            print("H1 順勢 + M15 回測成功: 準備買入")
                            print(f"確認多頭動能: RSI {curr_rsi:.2f}, Slope: {rsi_slope:.2f}")

                # 【空頭入場】
                # A. 大勢: H1 EMA50 < EMA200
                # B. 回測: M15 High 觸碰 EMA50 且 Close 收回下方
                # C. 動能: RSI 在 40-55
                elif is_h1_bearish and (m15_ema50[-1] < m15_ema200[-1]):
                    if curr_high >= curr_ema50 and curr_close < curr_ema50:
                        if (40 < curr_rsi < 55):
                            signal = -1
                            print("H1 逆勢 + M15 回測成功: 準備放空")
                            print(f"確認空頭動能: RSI {curr_rsi:.2f}, Slope: {rsi_slope:.2f}")


                # 只有 signal 變化時才跟單
                if signal != 0 and get_current_holding() == "None" and trade_count < 3:
                    atr14_val = calculate_atr(rates_m15, 14)[-1]
                    sl_dist = atr14_val * atr_mult_sl
                    tp_dist = atr14_val * atr_mult_tp
                    signal_Granted(master,symbol, [atr14_val], signal,tp_dist,sl_dist)
                    trade_count += 1

        time.sleep(1)

def signal_Granted(instance,symbol, atr, signal,tp_dist, sl_dist):
    """
    執行基於信號的交易，具備精確的 0.5% 風險控制與 XAUUSD 規格修正。
    """
    if not mt5.initialize(path=instance['mt5_path']):
        print(f"initialize() failed for {instance['instance_name']}")
        return
    
    # 獲取最新的 Tick 數據與 Symbol 規格
    tick = mt5.symbol_info_tick(symbol)
    symbol_info = mt5.symbol_info(symbol)

    account_info = mt5.account_info()
    if account_info is None or not account_info.trade_allowed:
        print(f"{instance['instance_name']}: 交易未啟用")
        return
    
    # --- 1. 計算進場價與止損空間 ---
    # 如果外部沒傳入距離，預設使用 ATR (SL=1.5x, TP=3.5x)
    atr_val = atr[-1] if isinstance(atr, (list, np.ndarray)) else atr
    balance = account_info.balance
    risk_amount = balance * instance['percentage_of_risk']
    print(f"Risk amount : {risk_amount}")
    #original lot calculation (work)
    #lot_raw = risk_per_trade / (sl_distance * contract_size)
    #lot = round_to_step(lot_raw, 0.01)

    #new lot calculation (test)
    # 1. 獲取當前品種的 Tick 資訊
    tick_size = symbol_info.trade_tick_size    # 最小跳動 (如 0.001 或 0.00001)
    tick_value = symbol_info.trade_tick_value  # 每一跳動值多少美金 (MT5 自動換算)

    # 2. 計算這筆止損總共包含多少個 Tick (點數)
    # sl_dist 是你的 1.0 ATR 距離
    sl_in_ticks = sl_dist / tick_size

    # 3. 計算正確手數
    # 公式：風險美金 / (總點數 * 每點美金價值)
    if sl_in_ticks > 0 and tick_value > 0:
        lot_raw = risk_amount / (sl_in_ticks * tick_value)
    else:
        lot_raw = symbol_info.volume_min

    # 4. 剩餘的 round_to_step 與 min/max 限制保持不變
    lot = round_to_step(lot_raw, symbol_info.volume_step)

    if signal == 1:  # BUY
        entry_price = tick.ask
        sl = entry_price - sl_dist
        tp = entry_price + tp_dist
        print(f"[{instance['instance_name']}] 執行 BUY | Risk: {risk_amount:.2f} | Lot: {lot:.2f} | SL: {sl:.2f} | TP: {tp:.2f}")
        place_trade(symbol, "BUY", lot, sl, tp, entry_price, instance['trading_company'])
        signal = 0
        
    elif signal == -1:  # SELL
        entry_price = tick.bid
        sl = entry_price + sl_dist
        tp = entry_price - tp_dist
        print(f"[{instance['instance_name']}] 執行 SELL | Risk: {risk_amount:.2f} | Lot: {lot:.2f} | SL: {sl:.2f} | TP: {tp:.2f}")
        place_trade(symbol, "SELL", lot, sl, tp, entry_price, instance['trading_company'])
        signal = 0
    time.sleep(900)

if __name__ == "__main__":
    trading_loop_master_slave(instances)