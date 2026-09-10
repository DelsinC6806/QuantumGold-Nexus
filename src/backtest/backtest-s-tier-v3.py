import pandas as pd
import numpy as np
import math

# --- Strategy B V3 Parameters ---
risk_per_trade_pct = 0.005  # Strict 0.5% risk profile
contract_size = 100
spread = 0.6               # Baseline spread padding
VP_LOOKBACK = 500          # M15 bars to map the Volume Profile grid
PRICE_BINS = 30            # Horizontal granularity of the profile matrix

def calculate_volume_profile_poc(m15_slice, volume_key, bins=30):
    lows = np.array([bar['low'] for bar in m15_slice])
    highs = np.array([bar['high'] for bar in m15_slice])
    tick_volumes = np.array([bar[volume_key] for bar in m15_slice])
    
    prices = np.concatenate([np.linspace(l, h, 5) for l, h in zip(lows, highs)])
    volumes = np.repeat(tick_volumes / 5, 5)
    
    counts, bin_edges = np.histogram(prices, bins=bins, weights=volumes)
    max_node_idx = np.argmax(counts)
    
    poc_price = (bin_edges[max_node_idx] + bin_edges[max_node_idx + 1]) / 2
    return poc_price

def calculate_volatility_metrics(m15_slice, lookback=20):
    closes = np.array([bar['close'] for bar in m15_slice[-lookback:]])
    highs = np.array([bar['high'] for bar in m15_slice[-lookback:]])
    lows = np.array([bar['low'] for bar in m15_slice[-lookback:]])
    
    sigma = np.std(closes)
    tr = np.maximum(highs[-14:] - lows[-14:], np.abs(highs[-14:] - closes[-15:-1]))
    atr_val = np.mean(tr)
    
    return sigma, atr_val

def backtest_strategy_b_s_tier(data, initial_balance=100000):
    balance = initial_balance
    lowest_balance = balance
    position = None
    trades = []
    today_trade_count = 0
    
    timestamps = [pd.to_datetime(bar['timestamp']) for bar in data]
    
    sample_bar = data[0]
    volume_key = next((k for k in ['tick_volume', 'volume', 'Volume', 'tick_vol'] if k in sample_bar), None)
    
    if volume_key is None:
        raise KeyError(f"Could not find a valid volume column. Available keys: {list(sample_bar.keys())}")
        
    print(f"Initiating Strategy B V3 (Gravity Engine) utilizing volume mapping key: '{volume_key}'...")
    
    for i in range(VP_LOOKBACK + 10, len(data)):
        ts = timestamps[i]
        
        if ts.hour == 6 and ts.minute == 0:
            today_trade_count = 0
            
        curr_candle = data[i]
        
        # --- 1. HANDLE RUNNING S-TIER POSITIONS (DEFENSIVE FIX APPLIED) ---
        if position is not None:
            high = curr_candle['high']
            low = curr_candle['low']
            exit_price = None
            
            if position['type'] == 'BUY':
                # Fixed: Whipsaw protection
                if low <= position['sl'] and high >= position['tp']:
                    exit_price = position['sl']
                elif low <= position['sl']:
                    exit_price = position['sl']
                elif high >= position['tp']:
                    exit_price = position['tp']
            elif position['type'] == 'SELL':
                # Fixed: Whipsaw protection
                if high >= position['sl'] and low <= position['tp']:
                    exit_price = position['sl']
                elif high >= position['sl']:
                    exit_price = position['sl']
                elif low <= position['tp']:
                    exit_price = position['tp']
                    
            if exit_price is not None:
                pnl = (exit_price - position['entry']) * contract_size * position['lot'] if position['type'] == 'BUY' else (position['entry'] - exit_price) * contract_size * position['lot']
                balance += pnl
                lowest_balance = min(lowest_balance, balance)
                
                trades.append({
                    'type': position['type'], 'entry': position['entry'], 'exit': exit_price, 'pnl': pnl, 'lot': position['lot']
                })
                position = None
                
        # --- 2. EVALUATE RE-ENGINEERED S-TIER SCANNER LOGIC (V3 GRAVITY) ---
        if position is None and today_trade_count < 3:
            
            m15_slice = data[i-VP_LOOKBACK:i]
            poc_price = calculate_volume_profile_poc(m15_slice, volume_key, bins=PRICE_BINS)
            
            # 30-bar structural boundaries
            local_highs = [bar['high'] for bar in m15_slice[-30:]]
            local_lows = [bar['low'] for bar in m15_slice[-30:]]
            structural_high = max(local_highs[:-1])
            structural_low = min(local_lows[:-1])
            
            # Volatility tracking
            sigma, atr_val = calculate_volatility_metrics(m15_slice, lookback=20)
            
            recent_bars = m15_slice[-20:]
            volumes = np.array([bar[volume_key] for bar in recent_bars])
            avg_volume = np.mean(volumes)
            std_volume = np.std(volumes)
            
            current_volume = curr_candle[volume_key]
            current_close = curr_candle['close']
            current_high = curr_candle['high']
            current_low = curr_candle['low']
            
            signal = 0
            
            # Volume filter set to a clean 1.75 SD for balanced entry validation
            if current_volume > (avg_volume + (1.75 * std_volume)):
                
                # Minimum target space requirement 
                required_clearance = max(atr_val * 1.25, sigma * 2)
                
                if current_low < structural_low and current_close > structural_low:
                    if (poc_price - current_close) > (required_clearance * 0.5):
                        signal = 1
                    
                elif current_high > structural_high and current_close < structural_high:
                    if (current_close - poc_price) > (required_clearance * 0.5):
                        signal = -1
                    
            # --- 3. EXECUTE POSITION ORDER BOOK ROUTING ---
            if signal != 0:
                sl_dist = max(atr_val * 1.25, sigma * 2)
                
                # FIX: Dropped to a realistic 1:1.5 RR for M15 inner-structure pulls
                tp_dist = sl_dist * 1.5  
                
                if signal == 1:
                    entry = current_close + spread
                    sl = entry - sl_dist
                    tp = entry + tp_dist
                    position = {
                        'type': 'BUY', 'entry': entry, 'sl': sl, 'tp': tp,
                        'lot': (balance * risk_per_trade_pct) / (sl_dist * contract_size)
                    }
                elif signal == -1:
                    entry = current_close - spread
                    sl = entry + sl_dist
                    tp = entry - tp_dist
                    position = {
                        'type': 'SELL', 'entry': entry, 'sl': sl, 'tp': tp,
                        'lot': (balance * risk_per_trade_pct) / (sl_dist * contract_size)
                    }
                    
                if position is not None:
                    position['lot'] = math.floor(position['lot'] / 0.01) * 0.01
                    position['lot'] = max(0.01, round(position['lot'], 2))
                    today_trade_count += 1

    if len(trades) == 0:
        print("Backtest processing finished: Zero signals qualified.")
        return

    win_trades = sum(1 for t in trades if t['pnl'] >= 0)
    lose_trades = sum(1 for t in trades if t['pnl'] < 0)
    
    print("\n================ STRATEGY B V3 BACKTEST PERFORMANCE ================")
    print(f"Total Transactions Logged: {len(trades)}")
    print(f"Final Account Balance:    ${balance:.2f}")
    print(f"Net Return Percentage:    {((balance - initial_balance) / initial_balance) * 100:.2f}%")
    print(f"Maximum Equity Drawdown Account Level: ${initial_balance - lowest_balance:.2f}")
    print(f"Winning Fills Count:      {win_trades}")
    print(f"Losing Fills Count:       {lose_trades}")
    print(f"True System Win Rate:     {(win_trades / len(trades)) * 100:.2f}%")
    print("================================================================")

if __name__ == "__main__":
    try:
        df = pd.read_csv("history_data.csv")
        data = df.to_dict('records')
        backtest_strategy_b_s_tier(data)
    except FileNotFoundError:
        print("Error: 'history_data.csv' missing from local directory.")