from loginToTradingView import login_to_tradingview
from loginToBroker import login_to_broker
from MetaTraderData import fetch_market_data
from strategy import calculate_fibonacci_levels,calculate_ema,calculate_swing_high_low,detect_trend,calculate_sl_tp_fixed,calculateSignal,backtest_strategy
from placetrade import place_trade
import MetaTrader5 as mt5
import time
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
test = False

def main():
    lot_size = 0.5
    currentHolding = "None"
    symbol = "XAUUSD"            
    
    if not mt5.initialize():
        print("MetaTrader 5 initialization failed")
        print(mt5.last_error())
        return None
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print(f"Failed to get symbol info for {symbol}")
        mt5.shutdown()
        return None
    print(f"Symbol: {symbol}")

    while True:
        now = datetime.now()
        current_minute = now.minute
        current_second = now.second

        if current_minute % 15 == 0 and current_second == 0:
            print("Current Time is:", now.strftime("%Y-%m-%d %H:%M:%S"))
            print("-----------------------------------------------------")
            print("Fetching market data...")

            data = fetch_market_data()
            if data is None:
                print("Failed to fetch market data")
                time.sleep(1)
                continue

            close_prices = [bar['close'] for bar in data]
            ema_20 = calculate_ema(close_prices, 20)
            print(f"EMA 20: {ema_20[-1]}")
            ema_50 = calculate_ema(close_prices, 50)
            print(f"EMA 50: {ema_50[-1]}")
            detected_trend = detect_trend(ema_20, ema_50)
            print(f"Detected Trend: {detected_trend}")

            swing_highs, swing_lows = calculate_swing_high_low(data)
            swing_high = swing_highs[-1]['price']
            swing_low = swing_lows[-1]['price']
            print(f"Swing High: {swing_high}, Swing Low: {swing_low}")
            fib_levels = calculate_fibonacci_levels(swing_high, swing_low, detected_trend)
            current_price = data[-1]['close']
            print(f"Current Price: {current_price}")
            print(f"Fibonacci Golden Range : \n[0.618]: {fib_levels['0.618']}, \n[0.5]: {fib_levels['0.5']}")

            if test:
                signal = "BUY"  # or "SELL" for testing sell flow
                print(f"[TEST MODE] Fake Signal: {signal}")
            else:
                signal = calculateSignal(detected_trend, fib_levels, current_price, currentHolding, ema_20, ema_50)
                print(f"Signal: {signal}")

            if signal == "BUY":
                print("Placing BUY trade...")
                sl_price = current_price - 2  # Example stop-loss price
                tp_price = current_price + 4
                if place_trade(symbol, "BUY", lot_size, sl_price, tp_price, current_price):
                    currentHolding = "BUY"
            elif signal == "SELL":
                print("Placing SELL trade...")
                sl_price = current_price + 2
                tp_price = current_price - 4
                if place_trade(symbol, "SELL", lot_size, sl_price, tp_price, current_price):
                    currentHolding = "SELL"

        time.sleep(1)

def load_history_data(filepath):
    # Example CSV columns: timestamp, open, high, low, close, volume
    df = pd.read_csv(filepath)
    # Convert DataFrame to list of dicts for compatibility
    data = df.to_dict('records')
    return data

if __name__ == "__main__":
    main()