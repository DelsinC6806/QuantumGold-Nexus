import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta
import time
import numpy as np
import pandas as pd
from strategy import calculate_ema, calculate_atr, calculate_rsi
from placetrade import place_trade
from threading import Thread
from multiprocessing import Process
import math
import os

fast = 5
slow = 20
atr_mult_sl = 2.0
atr_mult_tp = 5.0   #lower 3.5 to 3.0 for better result
contract_size = 100
symbol = ""
position = "None"
instances = [
    {                                                                       
        'mt5_path': 'C:/Program Files/MetaTrader 5/terminal64.exe',
        'instance_name': 'FXIFY',
        'symbol': ['GBPUSD.x','EURJPY.x','XAUUSD.x'],
        'trading_company': 'OANDA',
        'percentage_of_risk': 0.005,
        'position_holding': "None",
        'trade_count': 0,
        'magic_numeber': 111111
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

def get_h4_direction_and_atr(symbol):
    # Fetch last 20 bars
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H4, 0, 20)
    if rates is None or len(rates) < 2:
        return False, 0, 0
    
    df = pd.DataFrame(rates)
    
    # Index -2 is the candle that closed at 20:00 HKT
    last_candle = df.iloc[-2] 
    
    is_bullish = last_candle['close'] > last_candle['open']
    
    # Calculate ATR
    df['tr'] = df[['high', 'low', 'close']].apply(lambda x: x.max() - x.min(), axis=1)
    atr = df['tr'].rolling(14).mean().iloc[-1]
    
    return is_bullish, atr, last_candle['close']
def trading_loop(instances):

    master = instances[0]

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


            #Strategy start here

            if now.hour == 9 and now.minute == 15 and now.second == 1:
                print(f"Triggering trades for {now.date()}")
                for i, symbol in enumerate(master['symbol']):
                    signal, h4_atr, price = get_h4_direction_and_atr(symbol)

                    # If it's a Doji or error, skip this symbol entirely
                    if signal == 0:
                        print(f"Skipping {symbol}: H4 Bias is Indecisive (Doji) or No Data.")
                        continue
                    
                    for instance in instances:
                        rates_m15 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 1, 250)
                        atr14_val = calculate_atr(rates_m15, 14)[-1]
                        atr_sl = atr14_val * atr_mult_sl
                        
                        closes = np.array([x['close'] for x in rates_m15])
                        sigma = np.std(closes[-20:])
                        sd_sl = sigma * 2

                        sl_dist = max(atr_sl,sd_sl)
                        tp_dist = sl_dist * 1.1
                        signal_Granted(instance,instance['symbol'][i], signal,tp_dist,sl_dist)
        
        time.sleep(1)



def signal_Granted(instance,symbol, signal,tp_dist, sl_dist):
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
    balance = account_info.balance
    risk_amount = balance * instance['percentage_of_risk']
    print(f"Risk amount : {risk_amount}")

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

if __name__ == "__main__":
    trading_loop(instances)