import pandas as pd
import numpy as np
import math

# ==============================================================================
#                      STRATEGY CONFIG (VP + FVG ENTRY)
# ==============================================================================
RISK_PER_TRADE_PCT = 0.0075  
TARGET_RR_MULTIPLIER = 1.20  
VP_LOOKBACK_BARS = 96  
VP_TARGET_VOL_PCT = 0.68
VP_NUM_BINS = 80   
FVG_LOOKBACK_BARS = 10  # Number of recent bars to scan for an active FVG gap
SD_MULTIPLIER = 2.0  # Standard deviation multiplier for stop-loss distance
# ==============================================================================

CONTRACT_SIZE = 100
SPREAD = 0.00015 
COMMISSION_PER_LOT = 0.00    

def calculate_atr(highs, lows, closes, window=14):
    tr1 = highs - lows
    tr2 = np.zeros(len(closes))
    tr3 = np.zeros(len(closes))
    tr2[1:] = np.abs(highs[1:] - closes[:-1])
    tr3[1:] = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    return pd.Series(tr).rolling(window=window).mean().values

def calculate_volume_profile(window_df, num_bins=VP_NUM_BINS):
    price_min = window_df['low'].min()
    price_max = window_df['high'].max()
    
    if price_max == price_min:
        last_close = window_df['close'].iloc[-1]
        return last_close, last_close, last_close
    
    vol_col = 'tick_volume' if 'tick_volume' in window_df.columns else ('volume' if 'volume' in window_df.columns else None)
    volumes = window_df[vol_col].values if vol_col else np.ones(len(window_df))
    
    bins = np.linspace(price_min, price_max, num_bins + 1)
    closes = window_df['close'].values
    bin_indices = np.clip(np.digitize(closes, bins) - 1, 0, num_bins - 1)
    
    bin_volumes = np.zeros(num_bins)
    for idx, vol in zip(bin_indices, volumes):
        bin_volumes[idx] += vol
        
    poc = (bins[np.argmax(bin_volumes)] + bins[np.argmax(bin_volumes) + 1]) / 2.0
    
    total_vol = np.sum(bin_volumes)
    target_vol = total_vol * VP_TARGET_VOL_PCT  
    
    sorted_bin_indices = np.argsort(bin_volumes)[::-1]
    cum_vol = 0
    selected_bins = []
    
    for idx in sorted_bin_indices:
        cum_vol += bin_volumes[idx]
        selected_bins.append(idx)
        if cum_vol >= target_vol:
            break
            
    val = bins[min(selected_bins)]
    vah = bins[max(selected_bins) + 1]
    
    return vah, val, poc

def find_recent_fvg(df_slice, signal):
    """
    Scans the last few candles for a 3-candle Fair Value Gap (FVG).
    Bullish FVG: Low of Candle 3 > High of Candle 1. Gap level = High of Candle 1.
    Bearish FVG: High of Candle 3 < Low of Candle 1. Gap level = Low of Candle 1.
    """
    n = len(df_slice)
    if n < 3:
        return None

    # Scan backward through recent bars
    for idx in range(n - 1, n - FVG_LOOKBACK_BARS - 1, -1):
        if idx < 2:
            break
        c1 = df_slice.iloc[idx - 2]
        c3 = df_slice.iloc[idx]
        
        if signal == 1:  # Bullish FVG
            if c3['low'] > c1['high']:
                return c1['high']  # Top of Candle 1 acts as FVG demand retest level
        elif signal == -1:  # Bearish FVG
            if c3['high'] < c1['low']:
                return c1['low']   # Bottom of Candle 1 acts as FVG supply retest level
                
    return None

def backtest_time_based_single(data, initial_balance=50000):
    balance = initial_balance
    lowest_balance = balance
    position = None
    trades = []
    skipped_trades = 0
    
    timestamps = [pd.to_datetime(bar['timestamp']) for bar in data]
    
    df_temp = pd.DataFrame(data)
    df_temp['atr'] = calculate_atr(df_temp['high'].values, 
                                   df_temp['low'].values, 
                                   df_temp['close'].values, 
                                   window=14)
    df_temp['sigma'] = df_temp['close'].rolling(window=20).std()
    
    atrs = df_temp['atr'].values
    sigmas = df_temp['sigma'].values
    
    print(f"Initiating Time-Based Single Asset Backtest over {len(data)} periods...")

    for i in range(VP_LOOKBACK_BARS, len(data)):
        ts = timestamps[i]
        curr_candle = data[i]
        
        # === Position Management ===
        if position is not None:
            high = curr_candle['high']
            low = curr_candle['low']
            exit_price = None
            exit_reason = None
            
            if position['type'] == 'BUY':
                if low <= position['sl']:
                    exit_price = position['sl']
                    exit_reason = "LOSS"
                elif high >= position['tp']:
                    exit_price = position['tp']
                    exit_reason = "WIN"
            else:  # SELL
                if high >= position['sl']:
                    exit_price = position['sl']
                    exit_reason = "LOSS"
                elif low <= position['tp']:
                    exit_price = position['tp']
                    exit_reason = "WIN"
            
            if exit_price is not None:
                gross_pnl = (exit_price - position['entry']) * CONTRACT_SIZE * position['lot'] if position['type'] == 'BUY' else (position['entry'] - exit_price) * CONTRACT_SIZE * position['lot']
                pnl = gross_pnl - (position['lot'] * COMMISSION_PER_LOT)
                
                balance += pnl
                lowest_balance = min(lowest_balance, balance)
                
                trades.append({
                    'type': position['type'],
                    'entry': position['entry'],
                    'exit': exit_price,
                    'pnl': pnl,
                    'lot': position['lot'],
                    'reason': exit_reason,
                    'entry_ts': position['entry_ts'],
                    'exit_ts': ts,
                    'duration': ts - position['entry_ts']
                })
                position = None

        # === Entry Logic at 20:00 HKT (VP Filter + FVG Entry) ===
        if current_ts_is_time(ts, hour=20, minute=0) and position is None:
            h4_open = data[i-16]['open']
            h4_close = data[i-1]['close']
            signal = 1 if h4_close > h4_open else -1
            
            atr_val = atrs[i-1]
            sigma_val = sigmas[i-1]
            if np.isnan(atr_val) or np.isnan(sigma_val):
                continue
            
            current_price = curr_candle['open']
            
            # 1. Volume Profile Filter
            lookback_window = df_temp.iloc[i-VP_LOOKBACK_BARS:i]
            vah, val, _ = calculate_volume_profile(lookback_window, num_bins=VP_NUM_BINS)
            
            if signal == 1 and current_price <= vah:
                skipped_trades += 1
                continue
            elif signal == -1 and current_price >= val:
                skipped_trades += 1
                continue
            
            # 2. FVG / Supply-Demand Level Identification
            fvg_level = find_recent_fvg(df_temp.iloc[i-10:i], signal)
            
            if signal == 1:
                # If FVG found, anchor entry to the FVG gap level; otherwise default to VAH boundary
                entry_level = fvg_level if fvg_level is not None else vah
                entry = max(current_price, entry_level) + SPREAD
            else:
                entry_level = fvg_level if fvg_level is not None else val
                entry = min(current_price, entry_level) - SPREAD
            
            sl_dist = max(atr_val, sigma_val * SD_MULTIPLIER)
            tp_dist = sl_dist * TARGET_RR_MULTIPLIER
            
            risk_cash = balance * RISK_PER_TRADE_PCT
            lot_raw = risk_cash / (sl_dist * CONTRACT_SIZE)
            lot = max(0.01, math.floor(lot_raw * 100) / 100)  
            
            if signal == 1:
                position = {
                    'type': 'BUY',
                    'entry': entry,
                    'sl': entry - sl_dist + SPREAD,
                    'tp': entry + tp_dist, 
                    'lot': lot,
                    'sl_dist': sl_dist,
                    'entry_ts': ts
                }
            elif signal == -1:
                position = {
                    'type': 'SELL',
                    'entry': entry,
                    'sl': entry + sl_dist - SPREAD,
                    'tp': entry - tp_dist, 
                    'lot': lot,
                    'sl_dist': sl_dist,
                    'entry_ts': ts
                }

    # === Final Performance Report ===
    if not trades:
        print("No trades taken.")
        print(f"Trades Skipped by Volume Profile Filter: {skipped_trades}")
        return

    wins = [t for t in trades if t['reason'] == 'WIN']
    losses = [t for t in trades if t['reason'] == 'LOSS']
    
    win_trades = len(wins)
    lose_trades = len(losses)
    total_trades = len(trades)
    
    total_pnl = sum(t['pnl'] for t in trades)
    avg_win = sum(t['pnl'] for t in wins) / win_trades if wins else 0
    avg_loss = abs(sum(t['pnl'] for t in losses) / lose_trades) if losses else 0
    actual_rr = avg_win / avg_loss if avg_loss > 0 else 0
    avg_duration = sum((t['duration'] for t in trades), pd.Timedelta(0)) / len(trades)
    
    print("\n================ TIME-BASED + FVG PERFORMANCE ================")
    print(f"Total Transactions Executed: {total_trades}")
    print(f"Trades Skipped by VP Filter:  {skipped_trades}")
    print(f"Winning Trades:               {win_trades} ({(win_trades / total_trades) * 100:.1f}%)")
    print(f"Losing Trades:                {lose_trades} ({(lose_trades / total_trades) * 100:.1f}%)")
    print(f"Avg Win:                      ${avg_win:,.2f}")
    print(f"Avg Loss:                     -${avg_loss:,.2f}")
    print(f"Actual Risk:Reward:           1 : {actual_rr:.2f}")
    print(f"Final Balance:                ${balance:,.2f}")
    print(f"Net Return:                   {((balance - initial_balance) / initial_balance) * 100:,.2f}%")
    print(f"Maximum Drawdown:             ${initial_balance - lowest_balance:,.2f}")
    print(f"Total Net P&L:                ${total_pnl:,.2f}")
    print(f"Average Trade Duration:       {avg_duration}")
    print("===============================================================================")

def current_ts_is_time(ts, hour, minute):
    return ts.hour == hour and ts.minute == minute

if __name__ == "__main__":
    try:
        df = pd.read_csv("history_data.csv")
        data = df.to_dict('records')
        backtest_time_based_single(data)
    except FileNotFoundError:
        print("Error: 'history_data.csv' not found in current directory.")
    except Exception as e:
        print(f"Error during backtest: {e}")