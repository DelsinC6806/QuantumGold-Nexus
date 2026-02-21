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
atr_mult_tp = 3.5
contract_size = 100
symbol = ""
position = "None"
instances = [
    {                                                                       
        'mt5_path': 'C:/Program Files/MetaTrader 5/terminal64.exe',
        'instance_name': 'Fxify 50000',
        'symbol': 'XAUUSD.r',
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
            signal = 0
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


            # 15 minutes checking
            position = get_current_holding()

            # get 250 bars of m15 data
            rates = mt5.copy_rates_from_pos(master['symbol'], mt5.TIMEFRAME_M15, 0, 300)
            if rates is None or len(rates) < 250:
                print(f"{master['instance_name']}: 取得K線資料失敗")
                mt5.shutdown()
                time.sleep(2)
                continue

            # process new bar 
            latest_bar_ts = int(rates[-1]['time'])
            if last_bar_time == latest_bar_ts:
                time.sleep(1)
                continue
            last_bar_time = latest_bar_ts

            # calculate indicators (ema 5, 20 , 200, atr)
            close_prices = [bar['close'] for bar in rates]
            ema_fast = calculate_ema(close_prices, fast)
            ema_slow = calculate_ema(close_prices, slow)
            ema_200 = calculate_ema(close_prices, 200)
            atr14 = calculate_atr([{'high': bar['high'], 'low': bar['low'], 'close': bar['close']} for bar in rates], 14)
            atr250 = calculate_atr([{'high': bar['high'], 'low': bar['low'], 'close': bar['close']} for bar in rates], 250)
            print(f"{master['instance_name']}:[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] EMA 5: {ema_fast[-1]:.2f}, EMA 20: {ema_slow[-1]:.2f}, EMA 200: {ema_200[-1]:.2f}")
    
            #check trade count 
            if trade_count >= 3:
                print(f"{master['instance_name']}: 已達日內最大交易數，暫停交易")
                continue

            # Volatility filter（ATR 14 > ATR 250）
            print(f"{master['instance_name']}:[{now:%Y-%m-%d %H:%M:%S}] ATR14<{atr14[-1]:.2f}>  ATR250<{atr250[-1]:.2f}>")
            if np.isnan(atr14[-1]) or atr14[-1] < atr250[-1]:
                continue
            else:
                print(f"{master['instance_name']}: 波動率正常，準備下單")

            if ema_fast[-2] < ema_slow[-2] and ema_fast[-1] > ema_slow[-1]:
                signal = 1  # 多
                print(f"{master['instance_name']}: 多頭交叉，準備下多單")
            elif ema_fast[-2] > ema_slow[-2] and ema_fast[-1] < ema_slow[-1]:
                signal = -1 # 空
                print(f"{master['instance_name']}: 空頭交叉，準備下空單")
            else:
                signal = 0
                print(f"{master['instance_name']}: 無交叉，暫不下單")

            
            rsi = calculate_rsi(close_prices, 14)
            if signal == 1 and rsi[-1] < 50:  # 或 55
                signal = 0
                print(f"{master['instance_name']}: 多頭交叉，但 RSI < 50，取消多單")
            elif signal == -1 and rsi[-1] > 50:  # 或 45
                signal = 0
                print(f"{master['instance_name']}: 空頭交叉，但 RSI > 50，取消空單")

            if signal == 1 and rsi[-1] > 70:
                signal = 0
                print(f"{master['instance_name']}: 多頭交叉，但 RSI > 70，取消多單")
            elif signal == -1 and rsi[-1] < 30:
                signal = 0
                print(f"{master['instance_name']}: 空頭交叉，但 RSI < 30，取消空單")


            # 只有 signal 變化時才跟單
            if signal != 0 and position == "None":
                print(f"主信號: {signal}，所有 slave 開始跟單")
                trade_count += 1
                signal_Granted(master, close_prices, atr14, signal, position)
                #for slave in slaves:
                    #signal_Granted(slave, close_prices, atr14, signal, position)
                signal = 0

        time.sleep(1)

def signal_Granted(instance, close_prices, atr, signal, position,
                   tp_distance=None, sl_distance=None):
    """
    Execute a trade based on signal, with dynamic ATR-based TP/SL distances.
    """
    if not mt5.initialize(path=instance['mt5_path']):
        print(f"initialize() failed for {instance['symbol']} {instance['instance_name']}")
        return

    account_info = mt5.account_info()
    if account_info is None or not account_info.trade_allowed:
        print(f"{instance['instance_name']}: 交易未啟用")
        return

    balance = account_info.balance
    entry_price = close_prices[-1]
    atr_val = atr[-1]

    # If no dynamic distances passed, fall back to ATR multiples
    if tp_distance is None:
        tp_distance = atr_val * 1.5
    if sl_distance is None:
        sl_distance = atr_val * 1.0

    if signal == 1:  # BUY
        sl = entry_price - sl_distance
        tp = entry_price + tp_distance
        risk_per_trade = balance * instance['percentage_of_risk']
        lot_raw = risk_per_trade / (sl_distance * contract_size)
        lot = round_to_step(lot_raw, 0.01)
        print(f"{instance['instance_name']}: 主帳 BUY: lot={lot:.2f}, sl={sl:.2f}, tp={tp:.2f}")
        if(lot >= 0.16): #大於等於0.16手反向下單
            position = "SELL"
            place_trade(instance['symbol'], position, lot, tp, sl,entry_price, instance['trading_company'])
        else:
            position = "BUY"
            place_trade(instance['symbol'], position, lot, sl, tp,entry_price, instance['trading_company'])  
        

      


    elif signal == -1:  # SELL
        sl = entry_price + sl_distance
        tp = entry_price - tp_distance
        risk_per_trade = balance * instance['percentage_of_risk']
        lot_raw = risk_per_trade / (sl_distance * contract_size)
        lot = round_to_step(lot_raw, 0.01)
        print(f"{instance['instance_name']}: 主帳 SELL: lot={lot:.2f}, sl={sl:.2f}, tp={tp:.2f}")
        if(lot >= 0.16): #大於等於0.16手反向下單
            position = "BUY"
            place_trade(instance['symbol'], position, lot, tp, sl,entry_price, instance['trading_company'])
        else:
            position = "SELL"
            place_trade(instance['symbol'], position, lot, sl, tp,entry_price, instance['trading_company']) 
        mt5.shutdown()

if __name__ == "__main__":
    trading_loop_master_slave(instances)