import math
import numpy as np
import pandas as pd

# --- Core Strategy Constants ---
contract_size = 100
spread = 0.00015
RISK_PER_TRADE_PCT = 0.0075
COMMISSION_PER_LOT = 0.00
risk_reward_ratio = 1.6 # Default Risk:Reward ratio for TP calculation
# --- Dynamic Wick Strategy Parameters ---
WICK_MULTIPLIER = 4.0 
ATR_MA_PERIOD = 14  # Volatility gate: ATR must be > MA(ATR)


def calculate_atr(highs, lows, closes, window=14):
    tr1 = highs - lows
    tr2 = np.zeros(len(closes))
    tr3 = np.zeros(len(closes))
    tr2[1:] = np.abs(highs[1:] - closes[:-1])
    tr3[1:] = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    atr = pd.Series(tr).rolling(window=window).mean().values
    return atr


def backtest_wick_vs_body(
    data,
    initial_balance=50000,
    wick_mult=WICK_MULTIPLIER,
):
    balance = initial_balance
    lowest_balance = balance
    position = None
    trades = []

    timestamps = [pd.to_datetime(bar["timestamp"]) for bar in data]

    # Pre-calculate indicators
    df_temp = pd.DataFrame(data)
    df_temp["atr"] = calculate_atr(
        df_temp["high"].values,
        df_temp["low"].values,
        df_temp["close"].values,
        window=14,
    )
    df_temp["sigma"] = df_temp["close"].rolling(window=20).std()

    # Volatility Filter: ATR Moving Average
    df_temp["atr_ma"] = df_temp["atr"].rolling(window=ATR_MA_PERIOD).mean()

    # Calculate Candle Structure Metrics
    df_temp["upper_wick"] = df_temp["high"] - df_temp[["open", "close"]].max(
        axis=1
    )
    df_temp["lower_wick"] = (
        df_temp[["open", "close"]].min(axis=1) - df_temp["low"]
    )
    df_temp["body"] = (df_temp["close"] - df_temp["open"]).abs()

    atrs = df_temp["atr"].values
    sigmas = df_temp["sigma"].values
    atr_mas = df_temp["atr_ma"].values
    upper_wicks = df_temp["upper_wick"].values
    lower_wicks = df_temp["lower_wick"].values
    bodies = df_temp["body"].values

    print(
        f"Initiating Dynamic Wick Reversal Backtest over {len(data)} periods..."
    )
    print(f"Parameters -> Wick Multiplier: {wick_mult}x Candle Body Size")

    for i in range(50, len(data)):
        ts = timestamps[i]
        curr_candle = data[i]

        # === Manage Open Position ===
        if position is not None:
            high = curr_candle["high"]
            low = curr_candle["low"]
            exit_price = None
            exit_reason = None

            if position["type"] == "BUY":
                if low <= position["sl"]:
                    exit_price = position["sl"]
                    exit_reason = "LOSS"
                elif high >= position["tp"]:
                    exit_price = position["tp"]
                    exit_reason = "WIN"
            else:  # SELL
                if high >= position["sl"]:
                    exit_price = position["sl"]
                    exit_reason = "LOSS"
                elif low <= position["tp"]:
                    exit_price = position["tp"]
                    exit_reason = "WIN"

            if exit_price is not None:
                if position["type"] == "BUY":
                    gross_pnl = (
                        (exit_price - position["entry"])
                        * contract_size
                        * position["lot"]
                    )
                else:
                    gross_pnl = (
                        (position["entry"] - exit_price)
                        * contract_size
                        * position["lot"]
                    )

                commission_cost = position["lot"] * COMMISSION_PER_LOT
                pnl = gross_pnl - commission_cost

                balance += pnl
                lowest_balance = min(lowest_balance, balance)

                trades.append(
                    {
                        "type": position["type"],
                        "entry": position["entry"],
                        "exit": exit_price,
                        "pnl": pnl,
                        "lot": position["lot"],
                        "reason": exit_reason,
                        "entry_ts": position["entry_ts"],
                        "exit_ts": ts,
                        "duration": ts - position["entry_ts"],
                    }
                )
                position = None

        # === Dynamic Entry Logic (Evaluated on Completed Candle Bar i-1) ===
        if position is None:
            prev_atr = atrs[i - 1]
            prev_sigma = sigmas[i - 1]
            prev_atr_ma = atr_mas[i - 1]

            if (
                np.isnan(prev_atr)
                or np.isnan(prev_sigma)
                or np.isnan(prev_atr_ma)
            ):
                continue

            # Volatility Gate: Current M15 ATR must be expanding > MA(ATR)
            if prev_atr <= prev_atr_ma:
                continue

            prev_upper_wick = upper_wicks[i - 1]
            prev_lower_wick = lower_wicks[i - 1]
            prev_body = bodies[i - 1]

            # Avoid division by zero if candle body is 0 (Doji)
            effective_body = max(prev_body, 0.00001)

            # Rejection wick must be >= wick_mult times the candle body
            is_bullish_wick = (
                (prev_lower_wick / effective_body >= wick_mult)
                and (prev_lower_wick > prev_upper_wick)
            )

            is_bearish_wick = (
                (prev_upper_wick / effective_body >= wick_mult)
                and (prev_upper_wick > prev_lower_wick)
            )

            signal = 0
            if is_bullish_wick:
                signal = 1
            elif is_bearish_wick:
                signal = -1

            if signal == 0:
                continue

            # Risk Management Distance Logic
            atr_sl = prev_atr
            sd_sl = prev_sigma * 2.0
            sl_dist = max(atr_sl, sd_sl)
            tp_dist = sl_dist * risk_reward_ratio

            risk_cash = balance * RISK_PER_TRADE_PCT
            lot_raw = risk_cash / (sl_dist * contract_size)
            lot = max(0.01, math.floor(lot_raw * 100) / 100)

            current_price = curr_candle["open"]

            if signal == 1:  # BUY
                entry = current_price + spread
                position = {
                    "type": "BUY",
                    "entry": entry,
                    "sl": entry - sl_dist + spread,
                    "tp": entry + tp_dist,
                    "lot": lot,
                    "sl_dist": sl_dist,
                    "entry_ts": ts,
                }
            elif signal == -1:  # SELL
                entry = current_price - spread
                position = {
                    "type": "SELL",
                    "entry": entry,
                    "sl": entry + sl_dist - spread,
                    "tp": entry - tp_dist,
                    "lot": lot,
                    "sl_dist": sl_dist,
                    "entry_ts": ts,
                }

    # === Final Performance Report ===
    if len(trades) == 0:
        print("No trades triggered with current wick parameters.")
        return

    wins = [t for t in trades if t["reason"] == "WIN"]
    losses = [t for t in trades if t["reason"] == "LOSS"]

    win_trades = len(wins)
    lose_trades = len(losses)
    total_trades = len(trades)

    total_pnl = sum(t["pnl"] for t in trades)
    avg_win = sum(t["pnl"] for t in wins) / win_trades if wins else 0
    avg_loss = abs(sum(t["pnl"] for t in losses) / lose_trades) if losses else 0
    actual_rr = avg_win / avg_loss if avg_loss > 0 else 0

    avg_duration = sum(
        (t["duration"] for t in trades), pd.Timedelta(0)
    ) / len(trades)

    print("\n================ DYNAMIC WICK REVERSAL PERFORMANCE ================")
    print(f"Total Transactions:       {total_trades}")
    print(
        f"Winning Trades:           {win_trades} ({(win_trades / total_trades) * 100:.1f}%)"
    )
    print(
        f"Losing Trades:            {lose_trades} ({(lose_trades / total_trades) * 100:.1f}%)"
    )
    print(f"Avg Win:                  ${avg_win:,.2f}")
    print(f"Avg Loss:                 -${avg_loss:,.2f}")
    print(f"Actual Risk:Reward:       1 : {actual_rr:.2f}")
    print(f"Final Balance:            ${balance:,.2f}")
    print(
        f"Net Return:               {((balance - initial_balance) / initial_balance) * 100:,.2f}%"
    )
    print(f"Maximum Drawdown:         ${initial_balance - lowest_balance:,.2f}")
    print(f"Total Net P&L:            ${total_pnl:,.2f}")
    print(f"Average Trade Duration:   {avg_duration}")
    print("===============================================================================")


# === Run Backtest ===
if __name__ == "__main__":
    try:
        df = pd.read_csv("history_data.csv")
        data = df.to_dict("records")
        backtest_wick_vs_body(data, wick_mult=2.0)
    except FileNotFoundError:
        print("Error: 'history_data.csv' not found in current directory.")
    except Exception as e:
        print(f"Error during backtest: {e}")