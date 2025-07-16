import MetaTrader5 as mt5
from datetime import datetime, timedelta
import pandas as pd
def fetch_market_data():

    # Initialize MetaTrader 5 connection
    if not mt5.initialize():
        print("MetaTrader 5 initialization failed")
        print(mt5.last_error())
        return

    # Define the symbol and timeframe
    symbol = "XAUUSD"  # Gold/USD pair
    timeframe = mt5.TIMEFRAME_M15  # 15-minute candles
    limit = 500 # Fetch the last 100 candles
    tick = mt5.symbol_info_tick(symbol)
    # Get the current time and calculate the start time
    server_time = datetime.fromtimestamp(tick.time)
    end_time = server_time  # Adjust for the last tick
    start_time = end_time - timedelta(minutes=15 * limit)

    # Request historical data
    rates = mt5.copy_rates_range(symbol, timeframe, start_time, end_time)
    if rates is None:
        print(f"Failed to fetch data for {symbol}")
        print(mt5.last_error())
        mt5.shutdown()
        return
    
    #For debugging purposes
    #rates_frame = pd.DataFrame(rates)  # Convert to DataFrame for easier manipulation
    #rates_frame['time'] = pd.to_datetime(rates_frame['time'], unit='s')  # Convert time to datetime
    #print(rates_frame)  # Print the first few rows of the DataFrame

    data = []
    for rate in rates:
        data.append({
            "time": datetime.fromtimestamp(rate['time']),  # Convert Unix timestamp to datetime
            "open": rate['open'],
            "high": rate['high'],
            "low": rate['low'],
            "close": rate['close'],
            "volume": rate['tick_volume'],
        })


    # Fetch the latest tick data for the symbol
    tick = mt5.symbol_info_tick(symbol)

    print(f"Server Time: {server_time}")
    if tick is None:
        print(f"Failed to fetch tick data for {symbol}")
        print(mt5.last_error())
        mt5.shutdown()
        return None
    return data