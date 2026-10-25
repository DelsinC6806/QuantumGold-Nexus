import pandas as pd
import numpy as np
import math

# ==========================================
# --- Strategy Parameters & Constants ---
# ==========================================
CONTRACT_SIZE = 100
SPREAD = 0.00015 
RISK_PER_TRADE_PCT = 0.0075
COMMISSION_PER_LOT = 0.00    

# Technical Indicators & Rules
EMA_FAST = 20
EMA_SLOW = 50
ATR_WINDOW = 14
ATR_SL_MULT = 3.00          # SL distance multiplier relative to ATR
RR_RATIO = 2.0              # Risk:Reward Ratio for Take Profit
RETEST_EXPIRATION_BARS = 32  # Retest setup expires if not triggered within 16 bars

# ==========================================
# --- Helper Indicator Calculations ---
# ==========================================
def calculate_atr(highs, lows, closes, window=14):
    tr1 = highs - lows
    tr2 = np.zeros(len(closes))
    tr3 = np.zeros(len(closes))
    tr2[1:] = np.abs(highs[1:] - closes[:-1])
    tr3[1:] = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    atr = pd.Series(tr).rolling(window=window).mean().values
    return atr

def current_ts_is_time(ts, hour, minute):
    return ts.hour == hour and ts.minute == minute

# ==========================================
# --- Core Backtest Function ---
# ==========================================
def backtest_full_strategy(data, initial_balance=50000):
    balance = initial_balance
    lowest_balance = balance
    position = None
    pending_retest = None
    trades = []
    
    timestamps = [pd.to_datetime(bar['timestamp']) for bar in data]
    df_temp = pd.DataFrame(data)
    
    # Calculate Strategy Indicators
    df_temp['atr'] = calculate_atr(df_temp['high'].values, 
                                   df_temp['low'].values, 
                                   df_temp['close'].values, 
                                   window=ATR_WINDOW)
    df_temp['ema_fast'] = df_temp['close'].ewm(span=EMA_FAST, adjust=False).mean()
    df_temp['ema_slow'] = df_temp['close'].ewm(span=EMA_SLOW, adjust=False).mean()
    
    atrs = df_temp['atr'].values
    ema_fasts = df_temp['ema_fast'].values
    ema_slows = df_temp['ema_slow'].values
    
    print(f"Initiating Institutional Strategy Backtest over {len(data)} periods...\n")

    for i in range(50, len(data)):
        ts = timestamps[i]
        curr_candle = data[i]
        atr_val = atrs[i-1]
        ema_fast_val = ema_fasts[i-1]
        ema_slow_val = ema_slows[i-1]
        
        if np.isnan(atr_val) or np.isnan(ema_fast_val) or np.isnan(ema_slow_val):
            continue

        # =========================================================
        # 1. POSITION MANAGEMENT & TRAILING STOP LOSS
        # =========================================================
        if position is not None:
            high = curr_candle['high']
            low = curr_candle['low']
            close = curr_candle['close']
            exit_price = None
            exit_reason = None
            
            sl_dist = position['sl_dist']

            if position['type'] == 'BUY':
                # --- Trailing Stop Logic (BUY) ---
                # Stage 1: Break-Even Trigger at 1R profit
                if not position['be_triggered'] and high >= position['entry'] + sl_dist:
                    position['sl'] = position['entry'] + SPREAD
                    position['be_triggered'] = True
                
                # Stage 2: Dynamic ATR Trailing Stop (Active after BE)
                if position['be_triggered']:
                    new_sl = close - (atr_val * ATR_SL_MULT)
                    position['sl'] = max(position['sl'], new_sl)

                # --- Exit Execution Checks ---
                if low <= position['sl']:
                    exit_price = position['sl']
                    exit_reason = "SCRATCH" if position['be_triggered'] else "LOSS"
                elif high >= position['tp']:
                    exit_price = position['tp']
                    exit_reason = "WIN"

            else:  # SELL
                # --- Trailing Stop Logic (SELL) ---
                # Stage 1: Break-Even Trigger at 1R profit
                if not position['be_triggered'] and low <= position['entry'] - sl_dist:
                    position['sl'] = position['entry'] - SPREAD
                    position['be_triggered'] = True
                
                # Stage 2: Dynamic ATR Trailing Stop (Active after BE)
                if position['be_triggered']:
                    new_sl = close + (atr_val * ATR_SL_MULT)
                    position['sl'] = min(position['sl'], new_sl)

                # --- Exit Execution Checks ---
                if high >= position['sl']:
                    exit_price = position['sl']
                    exit_reason = "SCRATCH" if position['be_triggered'] else "LOSS"
                elif low <= position['tp']:
                    exit_price = position['tp']
                    exit_reason = "WIN"

            # Record Closed Trade
            if exit_price is not None:
                if position['type'] == 'BUY':
                    gross_pnl = (exit_price - position['entry']) * CONTRACT_SIZE * position['lot']
                else:
                    gross_pnl = (position['entry'] - exit_price) * CONTRACT_SIZE * position['lot']
                
                commission_cost = position['lot'] * COMMISSION_PER_LOT
                pnl = gross_pnl - commission_cost
                
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
                position = None  # Clear position

        # =========================================================
        # 2. BREAKOUT & RETEST EXECUTION
        # =========================================================
        if pending_retest is not None and position is None:
            retest_level = pending_retest['retest_level']
            signal_type = pending_retest['type']
            
            # Check if current candle retests the identified Bank Level
            is_retested = (curr_candle['low'] <= retest_level) if signal_type == 'BUY' else (curr_candle['high'] >= retest_level)
            
            if is_retested:
                # Re-verify Momentum before executing entry
                momentum_valid = (ema_fast_val > ema_slow_val) if signal_type == 'BUY' else (ema_fast_val < ema_slow_val)
                
                if momentum_valid:
                    sl_dist = atr_val * ATR_SL_MULT
                    tp_dist = sl_dist * RR_RATIO
                    
                    risk_cash = balance * RISK_PER_TRADE_PCT
                    lot_raw = risk_cash / (sl_dist * CONTRACT_SIZE)
                    lot = max(0.01, math.floor(lot_raw * 100) / 100)
                    
                    if signal_type == 'BUY':
                        entry = retest_level + SPREAD
                        position = {
                            'type': 'BUY',
                            'entry': entry,
                            'sl': entry - sl_dist,
                            'tp': entry + tp_dist,
                            'lot': lot,
                            'sl_dist': sl_dist,
                            'be_triggered': False,
                            'entry_ts': ts
                        }
                    else:  # SELL
                        entry = retest_level - SPREAD
                        position = {
                            'type': 'SELL',
                            'entry': entry,
                            'sl': entry + sl_dist,
                            'tp': entry - tp_dist,
                            'lot': lot,
                            'sl_dist': sl_dist,
                            'be_triggered': False,
                            'entry_ts': ts
                        }
                
                pending_retest = None  # Consume pending setup
                
            # Cancel setup if retest does not happen within timeout limit
            elif (i - pending_retest['index']) > RETEST_EXPIRATION_BARS:
                pending_retest = None

        # =========================================================
        # 3. SBU & BANK LEVEL SETUP IDENTIFICATION (20:00 UTC)
        # =========================================================
        if current_ts_is_time(ts, hour=20, minute=0) and position is None:
            # 1. Identify Bank/SBU Candle Levels across prior H4 block (16 sub-bars)
            h4_highs = [data[j]['high'] for j in range(i-16, i)]
            h4_lows = [data[j]['low'] for j in range(i-16, i)]
            
            h4_open = data[i-16]['open']
            h4_close = data[i-1]['close']
            
            bank_resistance = max(h4_highs)
            bank_support = min(h4_lows)
            
            # 2. Check Structural Direction + Momentum Filter
            bullish_structure = (h4_close > h4_open) and (ema_fast_val > ema_slow_val)
            bearish_structure = (h4_close < h4_open) and (ema_fast_val < ema_slow_val)
            
            if bullish_structure:
                pending_retest = {
                    'type': 'BUY',
                    'retest_level': bank_resistance,  # Breakout level to retest
                    'index': i
                }
            elif bearish_structure:
                pending_retest = {
                    'type': 'SELL',
                    'retest_level': bank_support,     # Breakout level to retest
                    'index': i
                }

    # ==========================================
    # --- Performance Summary Report ---
    # ==========================================
    if len(trades) == 0:
        print("No trades were executed during this backtest period.")
        return

    wins = [t for t in trades if t['reason'] == 'WIN']
    losses = [t for t in trades if t['reason'] == 'LOSS']
    scratches = [t for t in trades if t['reason'] == 'SCRATCH']
    
    total_trades = len(trades)
    win_trades = len(wins)
    lose_trades = len(losses)
    scratch_trades = len(scratches)
    
    total_pnl = sum(t['pnl'] for t in trades)
    avg_win = sum(t['pnl'] for t in wins) / win_trades if wins else 0
    avg_loss = abs(sum(t['pnl'] for t in losses) / lose_trades) if losses else 0
    actual_rr = avg_win / avg_loss if avg_loss > 0 else 0
    avg_duration = sum((t['duration'] for t in trades), pd.Timedelta(0)) / total_trades

    print("================ FULL STRATEGY PERFORMANCE REPORT ================")
    print(f"Total Trades:             {total_trades}")
    print(f"Winning Trades:           {win_trades} ({(win_trades / total_trades) * 100:.1f}%)")
    print(f"Losing Trades:            {lose_trades} ({(lose_trades / total_trades) * 100:.1f}%)")
    print(f"Scratches (Break-Even):   {scratch_trades} ({(scratch_trades / total_trades) * 100:.1f}%)")
    print(f"Average Win:              ${avg_win:,.2f}")
    print(f"Average Loss:             -${avg_loss:,.2f}")
    print(f"Realized Risk:Reward:     1 : {actual_rr:.2f}")
    print(f"Final Account Balance:    ${balance:,.2f}")
    print(f"Net Return:               {((balance - initial_balance) / initial_balance) * 100:,.2f}%")
    print(f"Maximum Drawdown:         ${initial_balance - lowest_balance:,.2f}")
    print(f"Total Net Profit:         ${total_pnl:,.2f}")
    print(f"Average Trade Duration:   {avg_duration}")
    print("==================================================================")

# ==========================================
# --- Script Execution ---
# ==========================================
if __name__ == "__main__":
    try:
        df = pd.read_csv("history_data.csv")
        data = df.to_dict('records')
        backtest_full_strategy(data)
    except FileNotFoundError:
        print("Error: 'history_data.csv' not found in current directory.")
    except Exception as e:
        print(f"Error executing backtest: {e}")