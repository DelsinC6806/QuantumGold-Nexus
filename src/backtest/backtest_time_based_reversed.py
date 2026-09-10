import pandas as pd
import numpy as np
import math

# --- Core Strategy Constants ---
fast = 5
slow = 20
contract_size = 100
# Realistic Spread for NY Open (e.g., 1.5 pips = 0.00015 for GBPUSD, adjust per pair)
spread = 0.00015 
RISK_PER_TRADE_PCT = 0.0075  # 0.75% risk per trade

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

def backtest_time_based_single_reversed(data, initial_balance=100000):
    balance = initial_balance
    lowest_balance = balance
    position = None
    trades = []
    
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
    
    print(f"Initiating REVERSED Time-Based Single Asset Backtest over {len(data)} periods...")

    for i in range(50, len(data)):
        ts = timestamps[i]
        curr_candle = data[i]
        
        # === 1. MANAGE OPEN POSITION ===
        if position is not None:
            high = curr_candle['high']
            low = curr_candle['low']
            exit_price = None
            exit_reason = None
            
            # The 0.6R Trigger Distance
            be_trigger_dist = position['sl_dist'] * 100000

            if position['type'] == 'BUY':
                # 1. Check if BE is triggered
                if not position.get('be_triggered', False) and high >= position['entry'] + be_trigger_dist:
                    # Move SL to entry + spread to ensure a true $0 scratch
                    position['sl'] = position['entry'] + spread 
                    position['be_triggered'] = True

                # 2. Check Exits (Loss/BE checked first for conservative intrabar modeling)
                if low <= position['sl']:
                    exit_price = position['sl']
                    exit_reason = "SCRATCH" if position.get('be_triggered', False) else "LOSS"
                elif high >= position['tp']:
                    exit_price = position['tp']
                    exit_reason = "WIN"

            else:  # SELL
                # 1. Check if BE is triggered
                if not position.get('be_triggered', False) and low <= position['entry'] - be_trigger_dist:
                    position['sl'] = position['entry'] - spread
                    position['be_triggered'] = True
                
                # 2. Check Exits
                if high >= position['sl']:
                    exit_price = position['sl']
                    exit_reason = "SCRATCH" if position.get('be_triggered', False) else "LOSS"
                elif low <= position['tp']:
                    exit_price = position['tp']
                    exit_reason = "WIN"
            
            if exit_price is not None:
                # Calculate PnL
                if position['type'] == 'BUY':
                    pnl = (exit_price - position['entry']) * contract_size * position['lot']
                else:
                    pnl = (position['entry'] - exit_price) * contract_size * position['lot']
                
                balance += pnl
                lowest_balance = min(lowest_balance, balance)
                
                trades.append({
                    'type': position['type'],
                    'entry': position['entry'],
                    'exit': exit_price,
                    'pnl': pnl,
                    'lot': position['lot'],
                    'reason': exit_reason
                })
                position = None

        # === 2. REVERSED ENTRY LOGIC AT 20:00 ===
        if current_ts_is_time(ts, hour=21, minute=30) and position is None:
            
            h4_open = data[i-16]['open']   # Open of previous H4 candle
            h4_close = data[i-1]['close']  # Close of previous H4 candle
            
            # REVERSED SIGNAL: If bullish, go short (-1). If bearish, go long (1).
            signal = -1 if h4_close > h4_open else 1
            
            atr_val = atrs[i-1]
            sigma_val = sigmas[i-1]
            
            if np.isnan(atr_val) or np.isnan(sigma_val):
                continue
            
            # Risk parameters
            atr_sl = atr_val
            sd_sl = sigma_val * 2
            sl_dist = max(atr_sl, sd_sl)
            tp_dist = sl_dist * 1.1  # Your 1.1x target
            
            # Position sizing
            risk_cash = balance * RISK_PER_TRADE_PCT
            lot_raw = risk_cash / (sl_dist * contract_size)
            lot = max(0.01, math.floor(lot_raw * 100) / 100)  
            
            current_price = curr_candle['open']
            
            if signal == 1:  # REVERSED BUY (Triggered on a bearish H4 close)
                entry = current_price + spread
                position = {
                    'type': 'BUY',
                    'entry': entry,
                    'sl': entry - sl_dist + spread, # Pay spread on SL trigger
                    'tp': entry + tp_dist, 
                    'lot': lot,
                    'sl_dist': sl_dist,
                    'be_triggered': False
                }
            else:  # REVERSED SELL (Triggered on a bullish H4 close)
                entry = current_price - spread
                position = {
                    'type': 'SELL',
                    'entry': entry,
                    'sl': entry + sl_dist - spread, # Pay spread on SL trigger
                    'tp': entry - tp_dist, 
                    'lot': lot,
                    'sl_dist': sl_dist,
                    'be_triggered': False
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
    
    print("\n================ REVERSED TIME-BASED SINGLE ASSET PERFORMANCE ================")
    print(f"Total Transactions:       {total_trades}")
    print(f"Winning Trades:           {win_trades} ({(win_trades / total_trades) * 100:.1f}%)")
    print(f"Losing Trades:            {lose_trades} ({(lose_trades / total_trades) * 100:.1f}%)")
    print(f"Break-Even (Scratches):   {scratch_trades} ({(scratch_trades / total_trades) * 100:.1f}%)")
    print(f"Avg Win:                  ${avg_win:,.2f}")
    print(f"Avg Loss:                 -${avg_loss:,.2f}")
    print(f"Actual Risk:Reward:       1 : {actual_rr:.2f}")
    print(f"Final Balance:            ${balance:,.2f}")
    print(f"Net Return:               {((balance - initial_balance) / initial_balance) * 100:,.2f}%")
    print(f"Maximum Drawdown:         ${initial_balance - lowest_balance:,.2f}")
    print(f"Total Net P&L:            ${total_pnl:,.2f}")
    print("===============================================================================")

def current_ts_is_time(ts, hour, minute):
    return ts.hour == hour and ts.minute == minute

# === Run Backtest ===
if __name__ == "__main__":
    try:
        df = pd.read_csv("history_data.csv")
        data = df.to_dict('records')
        backtest_time_based_single_reversed(data)
    except FileNotFoundError:
        print("Error: 'history_data.csv' not found in current directory.")
    except Exception as e:
        print(f"Error during backtest: {e}")