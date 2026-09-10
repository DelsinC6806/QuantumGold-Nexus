import pandas as pd
import numpy as np
import math

# --- Core Strategy Constants ---
fast = 5
slow = 20
contract_size = 100
spread = 0.00015
COMMISSION_PER_LOT = 0.00

# --- Card-Counting Bet Spread Parameters ---
MIN_RISK = 0.0000   # HARD SKIP: 0.0% Risk when table/deck parameters are toxic
BASE_RISK = 0.0075  # Core Base Bet: 0.75% under standard conditions
MAX_RISK = 0.050  # Maximum Allocation: 1.50% when deck is hot/expanding

def calculate_atr(highs, lows, closes, window=14):
    tr = np.zeros(len(closes))
    tr1 = highs - lows
    tr2 = np.zeros(len(closes))
    tr3 = np.zeros(len(closes))
    tr2[1:] = np.abs(highs[1:] - closes[:-1])
    tr3[1:] = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    atr = pd.Series(tr).rolling(window=window).mean().values
    return atr

def calculate_adx(high, low, close, window=14):
    df = pd.DataFrame({'high': high, 'low': low, 'close': close})
    plus_dm = df['high'].diff()
    minus_dm = df['low'].diff() * -1
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    tr = pd.concat([df['high'] - df['low'], 
                    abs(df['high'] - df['close'].shift()), 
                    abs(df['low'] - df['close'].shift())], axis=1).max(axis=1)
    
    atr = tr.rolling(window).mean()
    plus_di = 100 * (plus_dm.rolling(window).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window).mean() / atr)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(window).mean()
    return adx.values, plus_di.values, minus_di.values

def calculate_rsi(close, window=14):
    delta = pd.Series(close).diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.values

def backtest_time_based_single(data, initial_balance=50000):
    balance = initial_balance
    lowest_balance = balance
    position = None
    trades = []
   
    # Structural Audit Metrics
    skipped_friction_trap = 0
    skipped_asymmetry_trap = 0
    skipped_divergence_trap = 0
    skipped_low_adx = 0
    skipped_rsi_extreme = 0
   
    timestamps = [pd.to_datetime(bar['timestamp']) for bar in data]
   
    df_temp = pd.DataFrame(data)
   
    # Calculate key technical vectors
    df_temp['atr'] = calculate_atr(df_temp['high'].values,
                                   df_temp['low'].values,
                                   df_temp['close'].values,
                                   window=14)
    df_temp['sigma'] = df_temp['close'].rolling(window=20).std()
    df_temp['d1_sma20'] = df_temp['close'].rolling(window=1920, min_periods=50).mean()
   
    # New indicators
    adx_vals, _, _ = calculate_adx(df_temp['high'].values, 
                                   df_temp['low'].values, 
                                   df_temp['close'].values)
    rsi_vals = calculate_rsi(df_temp['close'].values)
    
    df_temp['adx'] = adx_vals
    df_temp['rsi'] = rsi_vals
   
    # Vector extraction for performance speed inside loop
    highs = df_temp['high'].values
    lows = df_temp['low'].values
    opens = df_temp['open'].values
    closes = df_temp['close'].values
    atrs = df_temp['atr'].values
    sigmas = df_temp['sigma'].values
    d1_smas = df_temp['d1_sma20'].values
    adxs = df_temp['adx'].values
    rsis = df_temp['rsi'].values
   
    print(f"Initiating Time-Based Single Asset Backtest over {len(data)} periods...")
    for i in range(50, len(data)):
        ts = timestamps[i]
        curr_candle = data[i]
       
        # === Manage Open Position ===
        if position is not None:
            high = curr_candle['high']
            low = curr_candle['low']
            exit_price = None
            exit_reason = None
           
            be_trigger_dist = position['sl_dist'] * 100000
            if position['type'] == 'BUY':
                if not position.get('be_triggered', False) and high >= position['entry'] + be_trigger_dist:
                    position['sl'] = position['entry'] + spread
                    position['be_triggered'] = True
                if low <= position['sl']:
                    exit_price = position['sl']
                    exit_reason = "SCRATCH" if position.get('be_triggered', False) else "LOSS"
                elif high >= position['tp']:
                    exit_price = position['tp']
                    exit_reason = "WIN"
            else: # SELL
                if not position.get('be_triggered', False) and low <= position['entry'] - be_trigger_dist:
                    position['sl'] = position['entry'] - spread
                    position['be_triggered'] = True
                if high >= position['sl']:
                    exit_price = position['sl']
                    exit_reason = "SCRATCH" if position.get('be_triggered', False) else "LOSS"
                elif low <= position['tp']:
                    exit_price = position['tp']
                    exit_reason = "WIN"
           
            if exit_price is not None:
                if position['type'] == 'BUY':
                    gross_pnl = (exit_price - position['entry']) * contract_size * position['lot']
                else:
                    gross_pnl = (position['entry'] - exit_price) * contract_size * position['lot']
               
                commission_cost = position['lot'] * COMMISSION_PER_LOT
                pnl = gross_pnl - commission_cost if exit_reason in ["WIN","LOSS"] else -commission_cost
               
                balance += pnl
                lowest_balance = min(lowest_balance, balance)
               
                exit_ts = ts
                duration = exit_ts - position['entry_ts']
               
                trades.append({
                    'type': position['type'],
                    'entry': position['entry'],
                    'exit': exit_price,
                    'pnl': pnl,
                    'lot': position['lot'],
                    'reason': exit_reason,
                    'entry_ts': position['entry_ts'],
                    'exit_ts': exit_ts,
                    'duration': duration,
                    'risk_pct': position['risk_pct']
                })
                position = None
        
        # === Entry Logic at 20:00 ===
        if ts.hour == 20 and ts.minute == 0 and position is None:
            atr_val = atrs[i-1]
            sigma_val = sigmas[i-1]
            d1_sma_val = d1_smas[i-1]
            adx_val = adxs[i-1]
            rsi_val = rsis[i-1]
            current_close = closes[i-1]
           
            if np.isnan(atr_val) or np.isnan(sigma_val) or np.isnan(d1_sma_val) or np.isnan(adx_val) or np.isnan(rsi_val):
                continue
               
            # Reconstruct the trailing 4-hour technical blocks (16 periods of 15-min data)
            h4_open = opens[i-16]
            h4_close = closes[i-1]
            signal = 1 if h4_close > h4_open else -1
           
            # ----------------------------------------------------
            # --- STRUCTURAL COLD DECK CONDITIONS (WONGING OUT) ---
            # ----------------------------------------------------
           
            # CONDITION 1: The Friction Trap (Spread-to-ATR Barrier)
            if atr_val == 0 or (spread / atr_val) > 0.12:
                skipped_friction_trap += 1
                continue
               
            # CONDITION 2: Volatility Asymmetry Trap (High-Chaos Over-Wicked Shoe)
            slice_highs = highs[i-64:i]
            slice_lows = lows[i-64:i]
            slice_opens = opens[i-64:i]
            slice_closes = closes[i-64:i]
           
            total_structural_height = np.sum(slice_highs - slice_lows)
            total_directional_body = np.sum(np.abs(slice_closes - slice_opens))
           
            if total_directional_body == 0 or (total_structural_height / total_directional_body) > 3.0:
                skipped_asymmetry_trap += 1
                continue
               
            # CONDITION 3: Multi-Timeframe Velocity Divergence Trap
            d1_trend = 1 if current_close > d1_sma_val else -1
            if signal != d1_trend:
                skipped_divergence_trap += 1
                continue
           
            # NEW COLD DECK: Low Trend Strength
            if adx_val < 20:
                skipped_low_adx += 1
                continue
           
            # NEW COLD DECK: Extreme RSI against signal
            if (signal == 1 and rsi_val > 70) or (signal == -1 and rsi_val < 30):
                skipped_rsi_extreme += 1
                continue
           
            # ----------------------------------------------------
            # --- HOT DECK ACCELERATION CRITERIA ---
            # ----------------------------------------------------
            is_hot_deck = (adx_val > 30) and (total_directional_body > 0) and (total_structural_height / total_directional_body < 1.8)
            
            if is_hot_deck:
                current_risk_pct = MAX_RISK
            else:
                current_risk_pct = BASE_RISK
           
            # --- Technical Execution Parameters ---
            atr_sl = atr_val
            sd_sl = sigma_val * 2
            sl_dist = max(atr_sl, sd_sl)
            tp_dist = sl_dist * 1.1
           
            risk_cash = balance * current_risk_pct
            lot_raw = risk_cash / (sl_dist * contract_size)
            lot = max(0.01, math.floor(lot_raw * 100) / 100)
           
            current_price = curr_candle['open']
           
            if signal == 1: # BUY
                entry = current_price + spread
                position = {
                    'type': 'BUY',
                    'entry': entry,
                    'sl': entry - sl_dist + spread,
                    'tp': entry + tp_dist,
                    'lot': lot,
                    'sl_dist': sl_dist,
                    'be_triggered': False,
                    'entry_ts': ts,
                    'risk_pct': current_risk_pct
                }
            else: # SELL
                entry = current_price - spread
                position = {
                    'type': 'SELL',
                    'entry': entry,
                    'sl': entry + sl_dist - spread,
                    'tp': entry - tp_dist,
                    'lot': lot,
                    'sl_dist': sl_dist,
                    'be_triggered': False,
                    'entry_ts': ts,
                    'risk_pct': current_risk_pct
                }
    
    # === Final Performance Report ===
    if len(trades) == 0:
        print("No trades executed.")
        return
    wins = [t for t in trades if t['reason'] == 'WIN']
    losses = [t for t in trades if t['reason'] == 'LOSS']
    scratches = [t for t in trades if t['reason'] == 'SCRATCH']
   
    win_trades = len(wins)
    lose_trades = len(losses)
    scratch_trades = len(scratches)
    total_trades = len(trades)
   
    total_pnl = sum(t['pnl'] for t in trades)
    avg_win = sum(t['pnl'] for t in wins) / win_trades if wins else 0
    avg_loss = abs(sum(t['pnl'] for t in losses) / lose_trades) if losses else 0
    actual_rr = avg_win / avg_loss if avg_loss > 0 else 0
   
    avg_duration = sum((t['duration'] for t in trades), pd.Timedelta(0)) / len(trades)
   
    print("\n================ OVERALL SYSTEM PERFORMANCE ================")
    print(f"Total Active Trades Taken: {total_trades}")
    print(f"Winning Trades (TP): {win_trades} ({(win_trades / total_trades) * 100:.1f}%)")
    print(f"Losing Trades (SL): {lose_trades} ({(lose_trades / total_trades) * 100:.1f}%)")
    print(f"Break-Even (Scratches): {scratch_trades} ({(scratch_trades / total_trades) * 100:.1f}%)")
    print(f"Avg Win: ${avg_win:,.2f}")
    print(f"Avg Loss: -${avg_loss:,.2f}")
    print(f"Actual Risk:Reward: 1 : {actual_rr:.2f}")
    print(f"Final Balance: ${balance:,.2f}")
    print(f"Net Total Return: {((balance - initial_balance) / initial_balance) * 100:,.2f}%")
    print(f"Maximum Drawdown: ${initial_balance - lowest_balance:,.2f}")
    print(f"Total Net P&L: ${total_pnl:,.2f}")
    print(f"Average Trade Duration: {avg_duration}")
   
    print("\n================ CARD COUNTING SHIELD EVASION LOGS ================")
    print(f"Friction Trap Skips (Spread/ATR > 0.12): {skipped_friction_trap} sessions")
    print(f"Asymmetry Trap Skips (Over-Wicked Chaos): {skipped_asymmetry_trap} sessions")
    print(f"Divergence Trap Skips (Anti-Daily Trend): {skipped_divergence_trap} sessions")
    print(f"Low ADX Skips (<20): {skipped_low_adx} sessions")
    print(f"Extreme RSI Skips: {skipped_rsi_extreme} sessions")
    print(f"Total Legally Evaded Cold Shoes: {skipped_friction_trap + skipped_asymmetry_trap + skipped_divergence_trap + skipped_low_adx + skipped_rsi_extreme} sessions")
   
    segments = [
        ("NEUTRAL CORE SHOE (0.75% Risk Setting)", BASE_RISK),
        ("HOT DECK ACCELERATION (1.50% Risk Setting)", MAX_RISK)
    ]
   
    for name, risk_val in segments:
        seg_trades = [t for t in trades if t.get('risk_pct', 0) == risk_val]
        total_seg = len(seg_trades)
       
        if total_seg == 0:
            print(f"\n--- {name} ---")
            print(" No trades triggered in this mathematical space.")
            continue
           
        seg_wins = len([t for t in seg_trades if t['reason'] == 'WIN'])
        seg_losses = len([t for t in seg_trades if t['reason'] == 'LOSS'])
        seg_scratches = len([t for t in seg_trades if t['reason'] == 'SCRATCH'])
        seg_pnl = sum(t['pnl'] for t in seg_trades)
       
        print(f"\n--- {name} ---")
        print(f" Allocated Trades: {total_seg}")
        print(f" Wins (Hit TP): {seg_wins} ({(seg_wins / total_seg) * 100:.1f}%)")
        print(f" Losses (Hit SL): {seg_losses} ({(seg_losses / total_seg) * 100:.1f}%)")
        print(f" Scratches (Break-even): {seg_scratches} ({(seg_scratches / total_seg) * 100:.1f}%)")
        print(f" Net Segment P&L: ${seg_pnl:,.2f}")
       
    print("===============================================================================")

def current_ts_is_time(ts, hour, minute):
    return ts.hour == hour and ts.minute == minute

# === Run Backtest ===
if __name__ == "__main__":
    try:
        df = pd.read_csv("history_data.csv")
        data = df.to_dict('records')
        backtest_time_based_single(data)
    except FileNotFoundError:
        print("Error: 'history_data.csv' not found in current directory.")
    except Exception as e:
        print(f"Error during backtest: {e}")