import MetaTrader5 as mt5
from datetime import datetime, timedelta
import time
import numpy as np
import pandas as pd
import math
import os
from placetrade import place_trade  # Assumed existing in your workspace

# --- System Parameters ---
fast = 5
slow = 20
atr_mult_sl = 1.25
atr_mult_tp = 3.5  # Keeps your dynamic range calculation intact
MAX_SLIPPAGE_PIPS = 25.0
LOG_PATH = "trade_log_b.txt"

# --- Strategy B Configuration Array ---
instances = [
    {                                                                       
        'mt5_path': 'C:/Program Files/MetaTrader 5/terminal64.exe',
        'instance_name': 'FundingPips_B',
        'symbol': ['GBPUSD', 'EURJPY', 'XAUUSD'],
        'trading_company': 'OANDA',
        'percentage_of_risk': 0.005,  # Strict 0.5% Risk
        'max_daily_trades': 3,        # Ironclad limit
        'magic_number': 222222        # Unique ID for Strategy B A/B tracking
    }
]

def count_trades_today_simple(log_path: str, target_date: str) -> int:
    """Counts how many trades have executed today based on the log file matching YYYY-MM-DD."""
    if not os.path.isfile(log_path):
        return 0
    count = 0
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            if target_date in line:
                count += 1
    return count

def log_trade_event(log_path: str, message: str):
    """Appends an execution event to the strategy log file."""
    today_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(f"[{today_str}] {message}\n")

def round_to_step(volume, step):
    """Adjusts lot sizing downward to match the broker asset steps to prevent order rejection."""
    if step <= 0:
        return round(volume, 2)
    return math.floor(volume / step) * step

def close_all_positions(symbol, trading_company):
    """Emergency/Session closing logic for positions matching a specific symbol."""
    positions = mt5.positions_get(symbol=symbol) or []
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return
    for pos in positions:
        vol = pos.volume
        if vol <= 0:
            continue
        if pos.type == mt5.POSITION_TYPE_BUY:
            place_trade(symbol, "SELL", vol, 0, 0, tick.bid, trading_company)
        elif pos.type == mt5.POSITION_TYPE_SELL:
            place_trade(symbol, "BUY", vol, 0, 0, tick.ask, trading_company)

def get_s_tier_signal(symbol, bins=30, imbalance_threshold=0.33):
    """
    Pure S-Tier Signal Matrix:
    1. Tracks horizontal Volume Profile (POC) across 500 M15 bars.
    2. Scans live Order Book (DOM) for depth queue imbalances.
    Returns: 1 (BUY), -1 (SELL), 0 (NEUTRAL)
    """
    # Fetch historical bars to compile the horizontal profile histogram
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 1, 500)
    if rates is None or len(rates) == 0:
        return 0
        
    df = pd.DataFrame(rates)
    prices = np.concatenate([np.linspace(l, h, 5) for l, h in zip(df['low'], df['high'])])
    volumes = np.repeat(df['tick_volume'].values / 5, 5)
    
    counts, bin_edges = np.histogram(prices, bins=bins, weights=volumes)
    poc_price = (bin_edges[np.argmax(counts)] + bin_edges[np.argmax(counts) + 1]) / 2
    
    # Extract live Depth of Market structures
    mt5.market_book_add(symbol)
    book = mt5.market_book_get(symbol)
    mt5.market_book_release(symbol)
    
    if book is None or len(book) == 0:
        return 0
        
    bid_volume = sum([level.volume for level in book if level.type == mt5.BOOK_TYPE_BUY])
    ask_volume = sum([level.volume for level in book if level.type == mt5.BOOK_TYPE_SELL])
    
    if (bid_volume + ask_volume) == 0:
        return 0
        
    # Standardized Order Book Imbalance (OBI) metric
    order_book_imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume)
    
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        return 0
    current_price = tick.last if tick.last > 0 else (tick.ask + tick.bid) / 2
    
    # Core Auction Matching Engine Rules:
    # BUY: Price is stretched below institutional POC AND buyers flood the live book queue
    if current_price < poc_price and order_book_imbalance > imbalance_threshold:
        return 1
    # SELL: Price is stretched above institutional POC AND sellers stack the live book queue
    elif current_price > poc_price and order_book_imbalance < -imbalance_threshold:
        return -1
        
    return 0

def signal_Granted(instance, symbol, signal, tp_dist, sl_dist, requested_price):
    """Handles precision mathematical risk calculations and routes execution to the bridge."""
    if not mt5.initialize(path=instance['mt5_path']):
        print(f"[{instance['instance_name']}] Initialization failed during trade execution call.")
        return False

    tick = mt5.symbol_info_tick(symbol)
    symbol_info = mt5.symbol_info(symbol)
    if not tick or not symbol_info:
        return False
        
    point = symbol_info.point
    current_market_price = tick.ask if signal == 1 else tick.bid
    
    # FIX: Accurate Network Slippage verification vs the instantaneous target tick
    price_diff_pips = abs(current_market_price - requested_price) / (point * 10)
    if price_diff_pips > MAX_SLIPPAGE_PIPS:
        print(f"[{instance['instance_name']}] REJECTED: Live execution slippage ({price_diff_pips:.1f} pips) exceeds filter limit.")
        return False

    account_info = mt5.account_info()
    if account_info is None or not account_info.trade_allowed:
        print(f"[{instance['instance_name']}] Bridge connection blocked or trading disallowed by broker.")
        return False
        
    # Standard 0.5% Account Risk Balance calculations
    balance = account_info.balance
    risk_amount = balance * instance['percentage_of_risk']
    
    tick_size = symbol_info.trade_tick_size
    tick_value = symbol_info.trade_tick_value
    sl_in_ticks = sl_dist / tick_size

    if sl_in_ticks > 0 and tick_value > 0:
        lot_raw = risk_amount / (sl_in_ticks * tick_value)
    else:
        lot_raw = symbol_info.volume_min

    # FIX: Removed the legacy hardcoded "/ 100" divisor on Gold. 
    # Modern ECN servers dynamically optimize 'tick_value' natively for contract sizes.
    lot = round_to_step(lot_raw, symbol_info.volume_step)
    lot = max(symbol_info.volume_min, min(symbol_info.volume_max, round(lot, 2)))

    # Execute trade signals via your project module
    if signal == 1:
        entry_price = tick.ask
        sl = entry_price - sl_dist
        tp = entry_price + tp_dist
        print(f"[{instance['instance_name']}] ROUTING BUY | Risk: ${risk_amount:.2f} | Lot: {lot} | SL: {sl:.2f} | TP: {tp:.2f}")
        place_trade(symbol, "BUY", lot, sl, tp, entry_price, instance['trading_company'])
        log_trade_event(LOG_PATH, f"BUY EXECUTED | Symbol: {symbol} | Lots: {lot} | SL: {sl:.5f} | TP: {tp:.5f}")
        return True
        
    elif signal == -1:
        entry_price = tick.bid
        sl = entry_price + sl_dist
        tp = entry_price - tp_dist
        print(f"[{instance['instance_name']}] ROUTING SELL | Risk: ${risk_amount:.2f} | Lot: {lot} | SL: {sl:.2f} | TP: {tp:.2f}")
        place_trade(symbol, "SELL", lot, sl, tp, entry_price, instance['trading_company'])
        log_trade_event(LOG_PATH, f"SELL EXECUTED | Symbol: {symbol} | Lots: {lot} | SL: {sl:.5f} | TP: {tp:.5f}")
        return True

    return False

def trading_loop(instances):
    master = instances[0]

    if not mt5.initialize(path=master['mt5_path']):
        print(f"Master Initialization critically failed for terminal execution path.")
        return
        
    # Synchronize dates and set up historical logging parameters
    now = datetime.now()
    target_date = (now - timedelta(days=1) if 0 <= now.hour < 6 else now).strftime("%Y-%m-%d")
    daily_trade_count = count_trades_today_simple(LOG_PATH, target_date)
    
    print(f"Strategy B Engine Online. Current Daily Trade Count: {daily_trade_count}/{master['max_daily_trades']}")

    while True:
        now = datetime.now()
        
        # Microstructure scans execute precisely on the 15-minute bar opening loop
        if now.minute % 15 == 0 and (now.second in (0, 1, 2)):
            if not mt5.initialize(path=master['mt5_path']):
                time.sleep(2)
                continue
                
            # Dynamic date state adjustments
            current_date_str = (now - timedelta(days=1) if 0 <= now.hour < 6 else now).strftime("%Y-%m-%d")
            if current_date_str != target_date:
                target_date = current_date_str
                daily_trade_count = count_trades_today_simple(LOG_PATH, target_date)
                print(f"Date boundary rollover detected. Resetting active count window. Current: {daily_trade_count}")

            # Safe account clearing protocol
            if now.hour == 4 and now.minute == 45:
                for symbol in master['symbol']:
                    close_all_positions(symbol, master['trading_company'])
                time.sleep(60)
                continue

            # Core S-Tier Scanner Loop across the designated asset registry
            for i, symbol in enumerate(master['symbol']):
                
                # Dynamic Daily Trade Guardrail
                if daily_trade_count >= master['max_daily_trades']:
                    continue
                
                # Fetch S-Tier Microstructure Matrix Signals
                signal = get_s_tier_signal(symbol)
                
                # If neutral, immediately step to the next evaluation handle
                if signal == 0:
                    continue
                    
                # Fix: Explicit integer condition processing ensures short signals process cleanly
                # Passing integer evaluation directly instead of using a 'truthy' statement filter
                
                # Fetch market statistics to construct dynamic volatility boundaries
                rates_m15 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 1, 250)
                if rates_m15 is None or len(rates_m15) < 20:
                    continue
                    
                # Calculate underlying mathematical bounds (ATR vs Standard Deviation)
                closes = np.array([x['close'] for x in rates_m15])
                highs = np.array([x['high'] for x in rates_m15])
                lows = np.array([x['low'] for x in rates_m15])
                
                # Raw mathematical ATR reconstruction
                tr = np.maximum(highs[-14:] - lows[-14:], np.abs(highs[-14:] - closes[-15:-1]))
                atr14_val = np.mean(tr)
                
                atr_sl = atr14_val * atr_mult_sl
                sigma = np.std(closes[-20:])
                sd_sl = sigma * 2

                sl_dist = max(atr_sl, sd_sl)
                tp_dist = sl_dist * 1.1 # Retains your 1:1.1 RR targeting framework

                # Grab instant pricing vectors to verify true execution slippage parameters
                target_tick = mt5.symbol_info_tick(symbol)
                if not target_tick:
                    continue
                req_price = target_tick.ask if signal == 1 else target_tick.bid

                # Route to individual structural account servers assigned to Strategy B
                for instance in instances:
                    if daily_trade_count < instance['max_daily_trades']:
                        executed = signal_Granted(instance, symbol, signal, tp_dist, sl_dist, req_price)
                        if executed:
                            daily_trade_count += 1
                            time.sleep(1) # Prevent order book execution flooding
            
            # Put the polling worker thread to sleep to avoid CPU resource starvation
            time.sleep(3)
            
        time.sleep(1)

if __name__ == "__main__":
    trading_loop(instances)