# Replace your EXIT LOGIC and METRICS block with this to see the real truth:

        elif position is not None:
            side = position['side']
            # Using High/Low for exits to be conservative
            hit_sl = (curr_bar['low'] <= position['sl'] if side == 1 else curr_bar['high'] >= position['sl'])
            hit_tp = (curr_bar['high'] >= position['tp'] if side == 1 else curr_bar['low'] <= position['tp'])
            
            if hit_sl or hit_tp:
                # REALISM: If both hit in the same bar, assume a loss (Slippage/Bad luck)
                if hit_sl and hit_tp:
                    exit_p = position['sl']
                else:
                    exit_p = position['sl'] if hit_sl else position['tp']

                pips = (exit_p - position['entry']) / pip_size if side == 1 else (position['entry'] - exit_p) / pip_size
                pnl = pips * position['lot'] * pip_val_std
                
                # Subtract commission (e.g., $7 per standard lot round turn)
                commission = position['lot'] * 7.0
                pnl -= commission
                
                balance += pnl
                trades.append({'pnl': pnl, 'win': pnl > 0})
                position = None

# --- NEW AUDIT METRICS ---
wins = [t['pnl'] for t in trades if t['pnl'] > 0]
losses = [t['pnl'] for t in trades if t['pnl'] <= 0]

avg_win_dollar = np.mean(wins) if wins else 0
avg_loss_dollar = abs(np.mean(losses)) if losses else 1 # avoid div by zero

realized_rr_math = avg_win_dollar / avg_loss_dollar

print(f"--- THE RAW TRUTH ---")
print(f"Total Profit/Loss: ${balance - initial_balance:,.2f}")
print(f"Actual Avg Win: ${avg_win_dollar:.2f}")
print(f"Actual Avg Loss: ${avg_loss_dollar:.2f}")
print(f"True Math R:R: {realized_rr_math:.2f}")