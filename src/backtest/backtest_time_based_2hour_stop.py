import pandas as pd
import numpy as np
import math

# --- Core Strategy Constants ---
contract_size = 100000          # 1 standard lot = 100,000 EUR
spread = 0.00015                # 1.5 pips
RISK_PER_TRADE_PCT = 0.0075     # 0.75%
COMMISSION_PER_LOT = 5.00       # Matches your broker exactly

def calculate_atr(highs, lows, closes, window=14):
    tr1 = highs - lows
    tr2 = np.abs(highs[1:] - closes[:-1])
    tr3 = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr1, np.maximum(np.pad(tr2, (1,0)), np.pad(tr3, (1,0))))
    atr = pd.Series(tr).rolling(window=window).mean().values
    return atr


def backtest_time_based_single(df, initial_balance=100000):
    balance = initial_balance
    lowest_balance = balance
    position = None
    trades = []
    
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['atr'] = calculate_atr(df['high'].values, df['low'].values, df['close'].values)
    df['sigma'] = df['close'].rolling(window=20).std()
    
    timestamps = df['timestamp'].values
    opens = df['open'].values
    highs = df['high'].values
    lows = df['low'].values
    closes = df['close'].values
    atrs = df['atr'].values
    sigmas = df['sigma'].values
    
    print(f"Starting backtest on {len(df)} bars...")

    for i in range(50, len(df)):
        ts = pd.Timestamp(timestamps[i])
        
        # === MANAGE OPEN POSITION ===
        if position is not None:
            high = highs[i]
            low = lows[i]
            exit_price = None
            exit_reason = None
            
            # Check if this trade has carried over to a different calendar day
            if ts.day != position['entry_time'].day:
                position['is_overnight'] = True
            
            if ts.hour == 5:  # Time exit at 22:00
                exit_price = opens[i]
                exit_reason = "TIME_LIMIT"
            elif position['type'] == 'BUY':
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
                # === REAL EURJPY P&L CALCULATION ===
                price_diff = (exit_price - position['entry']) if position['type'] == 'BUY' else (position['entry'] - exit_price)
                pnl_jpy = price_diff * contract_size * position['lot']
                
                # Convert JPY to USD using exit price
                pnl_usd = pnl_jpy / exit_price
                
                commission_cost = position['lot'] * COMMISSION_PER_LOT
                net_pnl = pnl_usd - commission_cost
                
                balance += net_pnl
                lowest_balance = min(lowest_balance, balance)
                
                trades.append({
                    'type': position['type'],
                    'entry_time': position['entry_time'],
                    'exit_time': ts,
                    'entry': position['entry'],
                    'exit': exit_price,
                    'lot': position['lot'],
                    'gross_pnl': round(pnl_usd, 2),
                    'commission': -commission_cost,
                    'net_pnl': round(net_pnl, 2),
                    'reason': exit_reason,
                    'is_overnight': position['is_overnight']
                })
                position = None

        # === ENTRY LOGIC ===
        if ts.hour == 20 and ts.minute == 0 and position is None:
            h4_open = opens[i-16] if i >= 16 else opens[0]
            h4_close = closes[i-1]
            
            signal = 1 if h4_close > h4_open else -1
            
            atr_val = atrs[i-1]
            sigma_val = sigmas[i-1]
            if np.isnan(atr_val) or np.isnan(sigma_val):
                continue
                
            sl_dist = max(atr_val, sigma_val * 2)
            tp_dist = sl_dist * 1.1
            
            # Position sizing based on USD risk
            risk_cash = balance * RISK_PER_TRADE_PCT
            risk_per_lot = (sl_dist * contract_size) / closes[i-1]   # Convert JPY risk to USD
            
            lot_raw = risk_cash / risk_per_lot
            lot = max(0.01, round(lot_raw * 100) / 100)
            
            current_price = opens[i]
            
            if signal == 1:  # BUY
                entry = current_price + spread / 2
                position = {
                    'type': 'BUY',
                    'entry_time': ts,
                    'entry': entry,
                    'sl': entry - sl_dist,
                    'tp': entry + tp_dist,
                    'lot': lot,
                    'is_overnight': False
                }
            else:  # SELL
                entry = current_price - spread / 2
                position = {
                    'type': 'SELL',
                    'entry_time': ts,
                    'entry': entry,
                    'sl': entry + sl_dist,
                    'tp': entry - tp_dist,
                    'lot': lot,
                    'is_overnight': False
                }

    # === Results & Advanced Overnight Analytics ===
    if not trades:
        print("No trades executed.")
        return
        
    total_trades = len(trades)
    wins = [t for t in trades if t['reason'] == 'WIN']
    losses = [t for t in trades if t['reason'] == 'LOSS']
    time_exits = [t for t in trades if t['reason'] == 'TIME_LIMIT']
    
    # Subgroup filtering
    overnight_trades = [t for t in trades if t['is_overnight']]
    same_day_trades = [t for t in trades if not t['is_overnight']]
    
    total_net_pnl = sum(t['net_pnl'] for t in trades)
    total_commission = sum(t['commission'] for t in trades)
    
    print("\n================ TIME-BASED SINGLE ASSET PERFORMANCE ================")
    print(f"Total Trades:             {total_trades}")
    print(f"Overall Win Rate:         {(len(wins)/total_trades*100):.1f}%")
    print(f"Winning Trades:           {len(wins)}")
    print(f"Losing Trades:            {len(losses)}")
    print(f"Time-Limit Exits:         {len(time_exits)}")
    print(f"Avg Win (Net):            ${sum(t['net_pnl'] for t in wins)/len(wins):,.2f}" if wins else "Avg Win: $0")
    print(f"Avg Loss (Net):           -${abs(sum(t['net_pnl'] for t in losses)/len(losses)):,.2f}" if losses else "Avg Loss: $0")
    
    print("\n-------------------- OVERNIGHT VS SAME-DAY BREAKDOWN --------------------")
    print(f"Same-Day Trades Closed:   {len(same_day_trades)} ({(len(same_day_trades)/total_trades*100):.1f}%)")
    if same_day_trades:
        sd_wins = len([t for t in same_day_trades if t['reason'] == 'WIN'])
        sd_losses = len([t for t in same_day_trades if t['reason'] == 'LOSS'])
        sd_time = len([t for t in same_day_trades if t['reason'] == 'TIME_LIMIT'])
        print(f"  -> Same-Day Wins:       {sd_wins} | Losses: {sd_losses} | Time Exits: {sd_time}")
        print(f"  -> Same-Day Net P&L:    ${sum(t['net_pnl'] for t in same_day_trades):,.2f}")

    print(f"Overnight Trades Held:    {len(overnight_trades)} ({(len(overnight_trades)/total_trades*100):.1f}%)")
    if overnight_trades:
        on_wins = len([t for t in overnight_trades if t['reason'] == 'WIN'])
        on_losses = len([t for t in overnight_trades if t['reason'] == 'LOSS'])
        on_time = len([t for t in overnight_trades if t['reason'] == 'TIME_LIMIT'])
        print(f"  -> Overnight Wins:      {on_wins} | Losses: {on_losses} | Time Exits: {on_time}")
        print(f"  -> Overnight Net P&L:   ${sum(t['net_pnl'] for t in overnight_trades):,.2f}")
    
    print("\n-------------------- ACCOUNT SUMMARY --------------------")
    print(f"Total Commission Paid:    ${abs(total_commission):,.2f}")
    print(f"Final Balance:            ${balance:,.2f}")
    print(f"Net Return:               {((balance - initial_balance) / initial_balance) * 100:,.2f}%")
    print(f"Maximum Drawdown:         ${initial_balance - lowest_balance:,.2f}")
    print(f"Total Net P&L:            ${total_net_pnl:,.2f}")
    print("===============================================================================")


if __name__ == "__main__":
    try:
        df = pd.read_csv("history_data.csv")
        backtest_time_based_single(df, initial_balance=100000)
    except Exception as e:
        print(f"Error: {e}")