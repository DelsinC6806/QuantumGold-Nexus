import pandas as pd
import numpy as np
import math
import sys

# --- Core Strategy Constants ---
CONTRACT_SIZE = 100
SPREAD = 0.00015             # 1.5 Pips (Adjust per asset. e.g., 0.015 for JPY pairs)
RISK_PER_TRADE_PCT = 0.0075  # Strict 0.75% risk per trade
INITIAL_BALANCE = 100000

# --- Adaptive Regime Settings ---
REGIME_LOOKBACK = 30         # Number of historical trades evaluated for performance
WIN_RATE_REVERSE_THRESHOLD = 0.44  # Flip to Reversed mode if trailing win rate falls below 44%
WIN_RATE_RESTORE_THRESHOLD = 0.52  # Return to Original mode if win rate climbs past 52%

# --- Safety Guardrail Limits ---
MAX_PROP_DRAWDOWN_PCT = 0.08 # Hard 8% absolute safety halt to protect 10% prop firm limits


def calculate_atr(highs, lows, closes, window=14):
    """Vectorized True Range + ATR calculation"""
    tr = np.zeros(len(closes))
    
    tr1 = highs - lows
    tr2 = np.zeros(len(closes))
    tr3 = np.zeros(len(closes))
    
    tr2[1:] = np.abs(highs[1:] - closes[:-1])
    tr3[1:] = np.abs(lows[1:] - closes[:-1])
    
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    atr = pd.Series(tr).rolling(window=window).mean().values
    return atr


def backtest_adaptive_time_based(data, initial_balance=INITIAL_BALANCE):
    balance = initial_balance
    lowest_balance = balance
    position = None
    trades = []
    
    # Adaptive state controllers
    reverse_mode = False
    regime_log = []
    
    timestamps = [pd.to_datetime(bar['timestamp']) for bar in data]
    
    # Pre-compute indicators
    df_temp = pd.DataFrame(data)
    df_temp['atr'] = calculate_atr(df_temp['high'].values, 
                                   df_temp['low'].values, 
                                   df_temp['close'].values, 
                                   window=14)
    df_temp['sigma'] = df_temp['close'].rolling(window=20).std()
    
    atrs = df_temp['atr'].values
    sigmas = df_temp['sigma'].values
    
    print(f"Initiating Adaptive Regime Time-Based Backtest over {len(data)} periods...")

    for i in range(50, len(data)):
        ts = timestamps[i]
        curr_candle = data[i]
        
        # === HARD GUARDRAIL CHECK ===
        current_drawdown_pct = (initial_balance - balance) / initial_balance
        if current_drawdown_pct >= MAX_PROP_DRAWDOWN_PCT:
            print(f"\n[CRITICAL HALT]: Maximum allowed equity drawdown reached ({current_drawdown_pct * 100:.2f}%). Execution stopped.")
            break
            
        # === 1. MANAGE OPEN POSITION ===
        if position is not None:
            high = curr_candle['high']
            low = curr_candle['low']
            exit_price = None
            exit_reason = None
            
            if position['type'] == 'BUY':
                # Check Exits (Loss checked first for conservative intrabar modeling)
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
                # Calculate PnL (Spread is accounted for inside directional execution prices)
                if position['type'] == 'BUY':
                    pnl = (exit_price - position['entry']) * CONTRACT_SIZE * position['lot']
                else:
                    pnl = (position['entry'] - exit_price) * CONTRACT_SIZE * position['lot']
                
                balance += pnl
                lowest_balance = min(lowest_balance, balance)
                
                trades.append({
                    'type': position['type'],
                    'entry': position['entry'],
                    'exit': exit_price,
                    'pnl': pnl,
                    'lot': position['lot'],
                    'reason': exit_reason,
                    'was_reversed': position['was_reversed']
                })
                position = None

        # === 2. DYNAMIC REGIME DETECTION EVALUATION ===
        if len(trades) >= REGIME_LOOKBACK and position is None:
            recent_trades = trades[-REGIME_LOOKBACK:]
            
            # Count performance metrics based purely on original structural intent
            # If trade matched baseline intent and won, or was reversed and lost -> original trend was working
            original_intent_wins = sum(
                1 for t in recent_trades 
                if (t['reason'] == 'WIN' and not t['was_reversed']) or (t['reason'] == 'LOSS' and t['was_reversed'])
            )
            original_intent_win_rate = original_intent_wins / REGIME_LOOKBACK
            
            # Shift regimes dynamically based on data health
            if original_intent_win_rate < WIN_RATE_REVERSE_THRESHOLD and not reverse_mode:
                reverse_mode = True
                regime_log.append({'timestamp': ts, 'mode': 'REVERSED', 'trigger_wr': original_intent_win_rate})
            elif original_intent_win_rate > WIN_RATE_RESTORE_THRESHOLD and reverse_mode:
                reverse_mode = False
                regime_log.append({'timestamp': ts, 'mode': 'ORIGINAL', 'trigger_wr': original_intent_win_rate})

        # === 3. TIME-BASED ENTRY LOGIC AT 20:00 HKT ===
        if current_ts_is_time(ts, hour=20, minute=0) and position is None:
            
            h4_open = data[i-16]['open']   # Open of previous H4 candle
            h4_close = data[i-1]['close']  # Close of previous H4 candle
            
            # 1 = Bullish continuation path / -1 = Bearish continuation path
            base_trend_signal = 1 if h4_close > h4_open else -1
            
            # Flip signal completely if regime filter is active
            final_signal = base_trend_signal if not reverse_mode else (base_trend_signal * -1)
            
            atr_val = atrs[i-1]
            sigma_val = sigmas[i-1]
            
            if np.isnan(atr_val) or np.isnan(sigma_val):
                continue
            
            # Define risk boundaries using 2 Standard Deviation vs ATR Max Envelope
            atr_sl = atr_val
            sd_sl = sigma_val * 2
            sl_dist = max(atr_sl, sd_sl)
            tp_dist = sl_dist * 1.1 
            
            # Position sizing auto-recalculation based on floating balance
            risk_cash = balance * RISK_PER_TRADE_PCT
            lot_raw = risk_cash / (sl_dist * CONTRACT_SIZE)
            lot = max(0.01, math.floor(lot_raw * 100) / 100)  
            
            current_price = curr_candle['open']
            
            if final_signal == 1:  # BUY EXECUTION
                entry = current_price + SPREAD
                position = {
                    'type': 'BUY',
                    'entry': entry,
                    'sl': entry - sl_dist + SPREAD, 
                    'tp': entry + tp_dist, 
                    'lot': lot,
                    'sl_dist': sl_dist,
                    'was_reversed': reverse_mode
                }
            else:  # SELL EXECUTION
                entry = current_price - SPREAD
                position = {
                    'type': 'SELL',
                    'entry': entry,
                    'sl': entry + sl_dist - SPREAD, 
                    'tp': entry - tp_dist, 
                    'lot': lot,
                    'sl_dist': sl_dist,
                    'was_reversed': reverse_mode
                }

    # === Performance Metric Reporting Engine ===
    if len(trades) == 0:
        print("No trades executed.")
        return

    wins = [t for t in trades if t['reason'] == 'WIN']
    losses = [t for t in trades if t['reason'] == 'LOSS']
    
    win_count = len(wins)
    loss_count = len(losses)
    total_trades = len(trades)
    
    total_pnl = sum(t['pnl'] for t in trades)
    avg_win = sum(t['pnl'] for t in wins) / win_count if win_count else 0
    avg_loss = abs(sum(t['pnl'] for t in losses) / loss_count) if loss_count else 0
    actual_rr = avg_win / avg_loss if avg_loss > 0 else 0
    
    print("\n================ ADAPTIVE SYSTEM PERFORMANCE REPORT ================")
    print(f"Total Transactions Executed: {total_trades}")
    print(f"Winning Trades:               {win_count} ({(win_count / total_trades) * 100:.1f}%)")
    print(f"Losing Trades:                {loss_count} ({(loss_count / total_trades) * 100:.1f}%)")
    print(f"Avg Win Payout:               ${avg_win:,.2f}")
    print(f"Avg Loss Outflow:             -${avg_loss:,.2f}")
    print(f"Mathematical Risk:Reward:     1 : {actual_rr:.2f}")
    print(f"Regime Shifts Triggered:      {len(regime_log)}")
    print(f"Historical Max Drawdown:      ${initial_balance - lowest_balance:,.2f} ({((initial_balance - lowest_balance)/initial_balance)*100:.2f}%)")
    print(f"Final Account Balance:        ${balance:,.2f}")
    print(f"Net Strategy Return:          {((balance - initial_balance) / initial_balance) * 100:,.2f}%")
    print("====================================================================\n")
    
    if len(regime_log) > 0:
        print("--- Last 5 Regime Transitions ---")
        for log in regime_log[-5:]:
            print(f"[{log['timestamp']}] Switched to {log['mode']} Mode (Trailing WR: {log['trigger_wr']*100:.1f}%)")


def current_ts_is_time(ts, hour, minute):
    return ts.hour == hour and ts.minute == minute


if __name__ == "__main__":
    try:
        # Load your multi-year M15 or hourly bar dataset
        df = pd.read_csv("history_data.csv")
        data = df.to_dict('records')
        backtest_adaptive_time_based(data)
    except FileNotFoundError:
        print("Error: 'history_data.csv' not found. Ensure file paths are mapped correctly.")
    except Exception as e:
        print(f"Execution Error: {e}")