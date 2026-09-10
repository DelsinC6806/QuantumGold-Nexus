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
MIN_RISK = 0.0030       # HARD SKIP: 0.0% Risk on your actual live account balance
BASE_RISK = 0.0075      # Core Base Bet: 0.75% under standard conditions
MAX_RISK = 0.01       # Maximum Allocation: 1.50% when deck is hot/expanding

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

def backtest_time_based_single(data, initial_balance=50000):
    balance = initial_balance
    lowest_balance = balance
    position = None
    trades = []
    
    # Shadow tracking arrays to audit skipped cold deck performance
    shadow_cold_trades = []
    
    timestamps = [pd.to_datetime(bar['timestamp']) for bar in data]
    df_temp = pd.DataFrame(data)
    
    # Calculate technical vectors
    df_temp['atr'] = calculate_atr(df_temp['high'].values, 
                                   df_temp['low'].values, 
                                   df_temp['close'].values, 
                                   window=14)
    df_temp['sigma'] = df_temp['close'].rolling(window=20).std()
    df_temp['d1_sma20'] = df_temp['close'].rolling(window=1920, min_periods=50).mean()
    
    highs = df_temp['high'].values
    lows = df_temp['low'].values
    opens = df_temp['open'].values
    closes = df_temp['close'].values
    atrs = df_temp['atr'].values
    sigmas = df_temp['sigma'].values
    d1_smas = df_temp['d1_sma20'].values
    
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
            else:  # SELL
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
                if position['is_shadow_cold']:
                    # Log to shadow auditor without touching real account balance
                    shadow_cold_trades.append({'reason': exit_reason})
                else:
                    # Execute normal active trade on capital account
                    if position['type'] == 'BUY':
                        gross_pnl = (exit_price - position['entry']) * contract_size * position['lot']
                    else:
                        gross_pnl = (position['entry'] - exit_price) * contract_size * position['lot']
                    
                    commission_cost = position['lot'] * COMMISSION_PER_LOT
                    pnl = gross_pnl - commission_cost if exit_reason in ["WIN","LOSS"] else -commission_cost
                    
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
                        'duration': ts - position['entry_ts'],
                        'risk_pct': position['risk_pct']
                    })
                position = None

        # === Entry Logic at 20:00 ===
        if current_ts_is_time(ts, hour=23, minute=0) and position is None:
            atr_val = atrs[i-1]
            sigma_val = sigmas[i-1]
            d1_sma_val = d1_smas[i-1]
            current_close = closes[i-1]
            
            if np.isnan(atr_val) or np.isnan(sigma_val) or np.isnan(d1_sma_val):
                continue
                
            h4_open = opens[i-16]
            h4_close = closes[i-1]
            signal = 1 if h4_close > h4_open else -1
            
            # --- Evaluate Structural Regimes ---
            is_cold_deck = False
            
            # 1. Friction Trap
            if atr_val == 0 or (spread / atr_val) > 0.12:
                is_cold_deck = True
                
            # 2. Volatility Asymmetry Trap
            slice_highs = highs[i-64:i]
            slice_lows = lows[i-64:i]
            slice_opens = opens[i-64:i]
            slice_closes = closes[i-64:i]
            total_structural_height = np.sum(slice_highs - slice_lows)
            total_directional_body = np.sum(np.abs(slice_closes - slice_opens))
            if total_directional_body == 0 or (total_structural_height / total_directional_body) > 3.0:
                is_cold_deck = True
                
            # 3. Multi-Timeframe Divergence Trap
            d1_trend = 1 if current_close > d1_sma_val else -1
            if signal != d1_trend:
                is_cold_deck = True
            
            # --- Determine Sizing and Mode ---
            if is_cold_deck:
                current_risk_pct = MIN_RISK
                is_shadow_cold = True
            elif total_directional_body > 0 and (total_structural_height / total_directional_body) < 1.8:
                current_risk_pct = MAX_RISK
                is_shadow_cold = False
            else:
                current_risk_pct = BASE_RISK
                is_shadow_cold = False
            
            # --- Technical Parameters Execution ---
            sl_dist = max(atr_val, sigma_val * 2)
            tp_dist = sl_dist * 1.1
            
            # For shadow tracking calculation, we assume a standard base sizing lot to measure outcomes fairly
            simulated_risk_pct = BASE_RISK if is_shadow_cold else current_risk_pct
            risk_cash = balance * simulated_risk_pct
            lot_raw = risk_cash / (sl_dist * contract_size)
            lot = max(0.01, math.floor(lot_raw * 100) / 100)  
            
            current_price = curr_candle['open']
            entry = current_price + spread if signal == 1 else current_price - spread
            sl_calc = entry - sl_dist + spread if signal == 1 else entry + sl_dist - spread
            tp_calc = entry + tp_dist if signal == 1 else entry - tp_dist
            
            position = {
                'type': 'BUY' if signal == 1 else 'SELL',
                'entry': entry,
                'sl': sl_calc,
                'tp': tp_calc, 
                'lot': lot,
                'sl_dist': sl_dist,
                'be_triggered': False,
                'entry_ts': ts,
                'risk_pct': current_risk_pct,
                'is_shadow_cold': is_shadow_cold
            }

    # === Final Performance Report ===
    if len(trades) == 0:
        print("No active trades executed.")
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
    
    print("\n================ OVERALL ACCOUNT PERFORMANCE ================")
    print(f"Total Active Trades Taken: {total_trades}")
    print(f"Winning Trades (TP):       {win_trades} ({(win_trades / total_trades) * 100:.1f}%)")
    print(f"Losing Trades (SL):        {lose_trades} ({(lose_trades / total_trades) * 100:.1f}%)")
    print(f"Avg Win:                  ${avg_win:,.2f}")
    print(f"Avg Loss:                 -${avg_loss:,.2f}")
    print(f"Actual Risk:Reward:       1 : {actual_rr:.2f}")
    print(f"Final Balance:            ${balance:,.2f}")
    print(f"Net Total Return:         {((balance - initial_balance) / initial_balance) * 100:,.2f}%")
    print(f"Maximum Drawdown:         ${initial_balance - lowest_balance:,.2f}")
    print(f"Total Net P&L:            ${total_pnl:,.2f}")
    
    print("\n================ ASYMMETRIC SHOE COUNT BREAKDOWN ================")
    
    # Audit 1: The Evaded Cold Deck (Shadow Math)
    total_cold = len(shadow_cold_trades)
    if total_cold > 0:
        cold_wins = len([t for t in shadow_cold_trades if t['reason'] == 'WIN'])
        cold_losses = len([t for t in shadow_cold_trades if t['reason'] == 'LOSS'])
        print(f"--- COLD DECK SHUFLLE (0.00% Risk - LEGALLY EVADED) ---")
        print(f"  Evaded Sessions:        {total_cold}")
        print(f"  Shadow Wins (Hit TP):   {cold_wins} ({(cold_wins / total_cold) * 100:.1f}%) <-- TRUE COLD WIN RATE")
        print(f"  Shadow Losses (Hit SL): {cold_losses} ({(cold_losses / total_cold) * 100:.1f}%)")
        print(f"  Saved Capital Exposure: Metaphorically Protected Accounts from -EV Space")
    else:
        print(f"--- COLD DECK SHUFLLE ---\n  No cold deck environments identified.")

    # Audit 2 & 3: Neutral and Hot Blocks
    segments = [
        ("NEUTRAL CORE SHOE (0.75% Risk Setting)", BASE_RISK),
        ("HOT DECK ACCELERATION (1.50% Risk Setting)", MAX_RISK)
    ]
    
    for name, risk_val in segments:
        seg_trades = [t for t in trades if t.get('risk_pct', 0) == risk_val]
        total_seg = len(seg_trades)
        
        if total_seg == 0:
            print(f"\n--- {name} ---\n  No trades triggered in this segment.")
            continue
            
        seg_wins = len([t for t in seg_trades if t['reason'] == 'WIN'])
        seg_losses = len([t for t in seg_trades if t['reason'] == 'LOSS'])
        seg_pnl = sum(t['pnl'] for t in seg_trades)
        
        print(f"\n--- {name} ---")
        print(f"  Allocated Trades:       {total_seg}")
        print(f"  Wins (Hit TP):          {seg_wins} ({(seg_wins / total_seg) * 100:.1f}%)")
        print(f"  Losses (Hit SL):        {seg_losses} ({(seg_losses / total_seg) * 100:.1f}%)")
        print(f"  Net Segment P&L:        ${seg_pnl:,.2f}")
        
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