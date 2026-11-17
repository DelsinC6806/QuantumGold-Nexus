import pandas as pd
import numpy as np
import math

# ==============================================================================
#           PURE "SNEAKY PIVOT" CONFIG (DYNAMIC DOUG RANGE TARGETS)
# ==============================================================================
RISK_PER_TRADE_PCT = 0.0075  
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

def calculate_magic_lines(df_history):
    """
    Calculates Range High/Low (Previous Day High/Low) and 
    Swing High/Low (Highest/Lowest prices prior to previous day).
    """
    df_temp = df_history.copy()
    df_temp['date'] = df_temp['timestamp'].dt.date
    unique_dates = df_temp['date'].unique()
    
    if len(unique_dates) < 2:
        return None, None, None, None
        
    prev_date = unique_dates[-2]
    prev_day_data = df_temp[df_temp['date'] == prev_date]
    
    range_high = prev_day_data['high'].max()
    range_low = prev_day_data['low'].min()
    
    prior_data = df_temp[df_temp['date'] < prev_date]
    if len(prior_data) > 0:
        swing_high = prior_data.tail(96 * 5)['high'].max()
        swing_low = prior_data.tail(96 * 5)['low'].min()
    else:
        swing_high = range_high
        swing_low = range_low
        
    return range_high, range_low, swing_high, swing_low

def backtest_sneaky_pivot_pure(data, initial_balance=50000):
    balance = initial_balance
    lowest_balance = balance
    position = None
    trades = []
    
    df_temp = pd.DataFrame(data)
    df_temp['timestamp'] = pd.to_datetime(df_temp['timestamp'])
    df_temp['atr'] = calculate_atr(df_temp['high'].values, 
                                   df_temp['low'].values, 
                                   df_temp['close'].values, 
                                   window=14)
    
    timestamps = df_temp['timestamp'].values
    atrs = df_temp['atr'].values
    
    print(f"Initiating Pure Sneaky Pivot (Dynamic Range TP) Backtest over {len(data)} periods...")

    for i in range(96 * 2, len(data)):  # Requires 2 days of historical data
        ts = pd.to_datetime(timestamps[i])
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

        # === Sneaky Pivot Trigger Check (15m Candles) ===
        if position is None and i >= 2:
            c1 = data[i-2]  # Test/Opening Candle
            c2 = data[i-1]  # Sneaky Candle (Reversal Confirmation)
            c3 = curr_candle # Entry Candle
            
            atr_val = atrs[i-1]
            if np.isnan(atr_val):
                continue
            
            # Calculate Magic Lines (Range High/Low & Swing High/Low)
            r_high, r_low, s_high, s_low = calculate_magic_lines(df_temp.iloc[:i])
            if r_high is None:
                continue
            
            # 1. Bullish Sneaky Pivot (Rejection at Range Low or Swing Low)
            at_support = (abs(c1['low'] - r_low) <= atr_val * 0.5) or (abs(c1['low'] - s_low) <= atr_val * 0.5) or (c1['low'] <= s_low)
            sneaky_bullish = (c2['close'] > c2['open'])  # Green confirmation candle
            breakout_bullish = c3['open'] >= c2['high']  # Candle 3 breaks Candle 2 high
            
            # 2. Bearish Sneaky Pivot (Rejection at Range High or Swing High)
            at_resistance = (abs(c1['high'] - r_high) <= atr_val * 0.5) or (abs(c1['high'] - s_high) <= atr_val * 0.5) or (c1['high'] >= s_high)
            sneaky_bearish = (c2['close'] < c2['open'])  # Red confirmation candle
            breakout_bearish = c3['open'] <= c2['low']   # Candle 3 breaks Candle 2 low
            
            signal = 0
            if at_support and sneaky_bullish and breakout_bullish:
                signal = 1
            elif at_resistance and sneaky_bearish and breakout_bearish:
                signal = -1
                
            if signal == 0:
                continue
                
            # Pattern-Based Stop Loss & Dynamic Range Take Profit Setup
            if signal == 1:
                entry = c3['open'] + SPREAD
                sl_price = min(c1['low'], c2['low']) - SPREAD
                sl_dist = max(entry - sl_price, atr_val * 0.5)
                
                # Dynamic Target: Target Range High (PDH) or Swing High depending on entry location
                tp_price = s_high if abs(c1['low'] - s_low) <= atr_val * 0.5 else r_high
                
                # Ensure minimum valid TP distance
                if tp_price <= entry:
                    tp_price = entry + (sl_dist * 1.2)
                
                risk_cash = balance * RISK_PER_TRADE_PCT
                lot_raw = risk_cash / (sl_dist * CONTRACT_SIZE)
                lot = max(0.01, math.floor(lot_raw * 100) / 100)  
                
                position = {
                    'type': 'BUY',
                    'entry': entry,
                    'sl': sl_price,
                    'tp': tp_price,
                    'lot': lot,
                    'entry_ts': ts
                }
            elif signal == -1:
                entry = c3['open'] - SPREAD
                sl_price = max(c1['high'], c2['high']) + SPREAD
                sl_dist = max(sl_price - entry, atr_val * 0.5)
                
                # Dynamic Target: Target Range Low (PDL) or Swing Low depending on entry location
                tp_price = s_low if abs(c1['high'] - s_high) <= atr_val * 0.5 else r_low
                
                # Ensure minimum valid TP distance
                if tp_price >= entry:
                    tp_price = entry - (sl_dist * 1.2)
                
                risk_cash = balance * RISK_PER_TRADE_PCT
                lot_raw = risk_cash / (sl_dist * CONTRACT_SIZE)
                lot = max(0.01, math.floor(lot_raw * 100) / 100)  
                
                position = {
                    'type': 'SELL',
                    'entry': entry,
                    'sl': sl_price,
                    'tp': tp_price,
                    'lot': lot,
                    'entry_ts': ts
                }

    # === Final Performance Report ===
    if not trades:
        print("No trades taken.")
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
    
    print("\n================ PURE SNEAKY PIVOT PERFORMANCE ================")
    print(f"Total Transactions Executed: {total_trades}")
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

if __name__ == "__main__":
    try:
        df = pd.read_csv("history_data.csv")
        data = df.to_dict('records')
        backtest_sneaky_pivot_pure(data)
    except FileNotFoundError:
        print("Error: 'history_data.csv' not found in current directory.")
    except Exception as e:
        print(f"Error during backtest: {e}")