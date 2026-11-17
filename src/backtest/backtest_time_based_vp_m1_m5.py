import json
import pandas as pd
import numpy as np
import math
import matplotlib.pyplot as plt
from typing import List, Dict, Optional

# ==============================================================================
#                              CONFIGURATION
# ==============================================================================
ACTIVE_SYMBOL          = "NAS100"     # "XAUUSD", "EURJPY", or "NAS100"
RISK_PER_TRADE_PCT     = 0.02
TARGET_RR_MULTIPLIER   = 1.5
VP_LOOKBACK_BARS       = 48
VP_TARGET_VOL_PCT      = 0.68
VP_NUM_BINS            = 50
SD_MULTIPLIER          = 0.7
USE_VOLUME_PROFILE     = True
USE_M1_M5_CONFIRMATION = False
USE_M1_CONFIRMATION    = False
USE_M5_CONFIRMATION    = False
M1_HISTORY_CSV         = "history_data_m1.csv"
M5_HISTORY_CSV         = "history_data_m5.csv"

# Kalman Filter
KALMAN_PROCESS_NOISE   = 1e-5   # Q
KALMAN_MEASURE_NOISE   = 1e-3   # R

# Instrument & costs
CONTRACT_SIZE          = 100
SPREAD                 = 0.00015
COMMISSION_PER_LOT     = 0.00
QUOTE_TO_ACCOUNT_CURRENCY = None  # Required for EURJPY; set JPY-to-account-currency rate.

# Risk / execution
MAX_ALLOWED_LOTS       = 20.0
MIN_LOT_RISK_CAP_MULTIPLIER = 999999
MOVE_SL_TO_BE          = False
BE_TRIGGER_R           = 1.0

# Session filter (HKT)
SCAN_START_HOUR        = 0
SCAN_END_HOUR          = 24
SCAN_INTERVAL_MIN      = 15

SYMBOL_BLOCKED_SLOTS_HKT = {
    "NAS100": {"00:00", "00:15", "00:30"},
    "XAUUSD": {
        "03:00", "03:15", "03:30", "03:45",
        "04:00", "04:15", "04:30", "04:45",
        "05:00", "05:15",
        "20:00", "20:15", "20:30", "21:00"
    },
    "EURJPY": {
        "07:00", "07:15", "07:45",
        "08:00", "08:15", "08:30", "08:45",
        "09:00", "09:15", "09:30"
    },
}

USE_HMM_FILTER         = False
HMM_PARAMS_JSON        = "hmm_params.json"
HMM_TREND_THRESHOLD    = 0.15


# ==============================================================================
#                              HELPERS
# ==============================================================================
def compute_causal_hmm_probs(closes: np.ndarray, params_path: str) -> tuple[np.ndarray, np.ndarray]:
    """
    Loads frozen HMM parameters from JSON and computes zero-lookahead
    P(Trend) and P(Spike) arrays aligned to closes[].
    """
    with open(params_path, "r") as f:
        cfg = json.load(f)

    vol_window = cfg["vol_window"]
    trend_idx = cfg["trend_state"]
    spike_idx = cfg["spike_state"]
    pi = np.array(cfg["pi"], dtype=float)
    A = np.array(cfg["A"], dtype=float)
    means = np.array(cfg["means"], dtype=float)
    covs = np.array(cfg["covs"], dtype=float)

    T = len(closes)
    K, D = means.shape
    p_trend = np.zeros(T)
    p_spike = np.zeros(T)

    # Match exact feature engineering from trainHMM.py (* 100.0 percentage scale)
    log_ret = np.zeros(T)
    log_ret[1:] = np.log(closes[1:] / closes[:-1]) * 100.0
    abs_ret = np.abs(log_ret)
    realized_vol = pd.Series(log_ret).rolling(vol_window).std(ddof=0).to_numpy()

    reg_covs = [covs[j] + 1e-6 * np.eye(D) for j in range(K)]
    inv_covs = [np.linalg.inv(reg_covs[j]) for j in range(K)]
    norm_consts = [
        1.0 / np.sqrt(((2.0 * np.pi) ** D) * np.linalg.det(reg_covs[j]))
        for j in range(K)
    ]

    alpha = pi.copy()
    started = False

    for t in range(1, T):
        if np.isnan(realized_vol[t]):
            continue
        if started:
            alpha = alpha @ A
        started = True

        x = np.array([abs_ret[t], realized_vol[t]])
        likelihoods = np.zeros(K)
        for j in range(K):
            diff = x - means[j]
            exponent = -0.5 * (diff @ inv_covs[j] @ diff)
            likelihoods[j] = norm_consts[j] * np.exp(exponent)

        unnorm = alpha * likelihoods
        alpha = unnorm / (np.sum(unnorm) + 1e-16)
        p_trend[t] = alpha[trend_idx]
        p_spike[t] = alpha[spike_idx]

    return p_trend, p_spike


def run_kalman_filter_2D(closes: np.ndarray,
                         process_noise: float = 1e-5,
                         measurement_noise: float = 1e-3) -> float:
    """2-state constant-velocity Kalman filter. Returns estimated drift (velocity)."""
    if len(closes) < 2:
        return 0.0

    F = np.array([[1.0, 1.0],
                  [0.0, 1.0]])
    H = np.array([[1.0, 0.0]])
    Q = np.eye(2) * process_noise
    R = np.array([[measurement_noise]])

    x = np.array([[closes[0]], [0.0]])
    P = np.eye(2)

    for z in closes:
        x = F @ x
        P = F @ P @ F.T + Q
        y = z - (H @ x)[0, 0]
        S = (H @ P @ H.T + R)[0, 0]
        K = (P @ H.T) / S
        x = x + K * y
        P = (np.eye(2) - K @ H) @ P

    return float(x[1, 0])


def calculate_atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray,
                  window: int = 14) -> np.ndarray:
    tr1 = highs - lows
    tr2 = np.zeros_like(closes)
    tr3 = np.zeros_like(closes)
    tr2[1:] = np.abs(highs[1:] - closes[:-1])
    tr3[1:] = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    return pd.Series(tr).rolling(window=window, min_periods=window).mean().values


def calculate_volume_profile(window_df: pd.DataFrame,
                             num_bins: int = VP_NUM_BINS) -> tuple:
    price_min = window_df["low"].min()
    price_max = window_df["high"].max()

    if price_max <= price_min or len(window_df) < 5:
        last = window_df["close"].iloc[-1]
        return last, last, last

    vol_col = "tick_volume" if "tick_volume" in window_df.columns else \
              "volume" if "volume" in window_df.columns else None
    volumes = window_df[vol_col].values if vol_col else np.ones(len(window_df))

    bins = np.linspace(price_min, price_max, num_bins + 1)
    closes = window_df["close"].values
    bin_indices = np.clip(np.digitize(closes, bins) - 1, 0, num_bins - 1)

    bin_volumes = np.zeros(num_bins)
    for idx, vol in zip(bin_indices, volumes):
        bin_volumes[idx] += vol

    poc_idx = int(np.argmax(bin_volumes))
    poc = (bins[poc_idx] + bins[poc_idx + 1]) / 2.0

    total_vol = bin_volumes.sum()
    target_vol = total_vol * VP_TARGET_VOL_PCT
    sorted_idx = np.argsort(bin_volumes)[::-1]

    cum = 0.0
    selected = []
    for idx in sorted_idx:
        cum += bin_volumes[idx]
        selected.append(idx)
        if cum >= target_vol:
            break

    val = bins[min(selected)]
    vah = bins[max(selected) + 1]
    return vah, val, poc


def is_scan_time(ts: pd.Timestamp,
                 start_hour: int = SCAN_START_HOUR,
                 end_hour: int = SCAN_END_HOUR,
                 interval: int = SCAN_INTERVAL_MIN) -> bool:
    if ts.hour < start_hour or ts.hour > end_hour:
        return False
    if ts.hour == end_hour and ts.minute > 0:
        return False
    total_minutes = (ts.hour - start_hour) * 60 + ts.minute
    return total_minutes % interval == 0


def current_ts_is_scan_time(ts, start_hour=20, end_hour=24, interval_minutes=15):
    return is_scan_time(ts, start_hour, end_hour, interval_minutes)


def is_blocked_slot(ts: pd.Timestamp, blocked_slots: set) -> bool:
    return ts.strftime("%H:%M") in blocked_slots


def _prepare_confirmation_rates(data: List[Dict], timeframe: str) -> pd.DataFrame:
    rates = pd.DataFrame(data)
    if rates.empty:
        raise ValueError(f"{timeframe} history is empty.")
    required = {"timestamp", "open", "high", "low", "close"}
    missing = required.difference(rates.columns)
    if missing:
        raise ValueError(
            f"{timeframe} history is missing required columns: {', '.join(sorted(missing))}."
        )

    rates["timestamp"] = pd.to_datetime(rates["timestamp"])
    if rates["timestamp"].isna().any():
        raise ValueError(f"{timeframe} history contains missing timestamps.")
    rates = rates.sort_values("timestamp").reset_index(drop=True)
    if rates["timestamp"].duplicated().any():
        raise ValueError(f"{timeframe} history contains duplicate timestamps.")

    price_columns = ["open", "high", "low", "close"]
    rates[price_columns] = rates[price_columns].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(rates[price_columns].to_numpy(dtype=float)).all():
        raise ValueError(f"{timeframe} history contains non-finite prices.")
    if (rates[price_columns] <= 0).any().any():
        raise ValueError(f"{timeframe} history contains non-positive prices.")
    return rates


def confirm_m1_m5_entry(signal: int,
                        atr_m15: float,
                        m5_rates: Optional[pd.DataFrame],
                        m1_rates: Optional[pd.DataFrame]) -> bool:
    if signal not in (-1, 1):
        raise ValueError("Signal must be 1 (BUY) or -1 (SELL).")
    if not math.isfinite(atr_m15) or atr_m15 <= 0:
        return False
    if (m5_rates is not None and len(m5_rates) < 24) or \
            (m1_rates is not None and len(m1_rates) < 3):
        return False

    if m5_rates is not None:
        m5_window = m5_rates.iloc[-24:]
        m5_closes = m5_window["close"].to_numpy(dtype=float)
        drift_m5 = run_kalman_filter_2D(
            np.log(m5_closes),
            process_noise=KALMAN_PROCESS_NOISE,
            measurement_noise=KALMAN_MEASURE_NOISE,
        )
        if (signal == 1 and drift_m5 <= 0) or (signal == -1 and drift_m5 >= 0):
            return False

        last_m5 = m5_window.iloc[-1]
        m5_range = last_m5["high"] - last_m5["low"]
        if m5_range <= 0:
            return False
        if signal == 1:
            if last_m5["close"] <= last_m5["open"] or \
                    (last_m5["close"] - last_m5["low"]) / m5_range < 0.6:
                return False
        elif last_m5["close"] >= last_m5["open"] or \
                (last_m5["high"] - last_m5["close"]) / m5_range < 0.6:
            return False

    if m1_rates is not None:
        m1_window = m1_rates.iloc[-3:]
        m1_range = m1_window["high"].max() - m1_window["low"].min()
        if m1_range > 1.2 * atr_m15:
            return False
    return True


# ==============================================================================
#                              BACKTEST ENGINE
# ==============================================================================
def backtest_kalman(data: List[Dict],
                    symbol: str = ACTIVE_SYMBOL,
                    initial_balance: float = 50000.0,
                    data_m1: Optional[List[Dict]] = None,
                    data_m5: Optional[List[Dict]] = None,
                    use_m1_m5_confirmation: bool = USE_M1_M5_CONFIRMATION,
                    use_m1_confirmation: bool = USE_M1_CONFIRMATION,
                    use_m5_confirmation: bool = USE_M5_CONFIRMATION) -> Dict:
    if symbol not in SYMBOL_BLOCKED_SLOTS_HKT:
        raise ValueError(f"No blocked-slot configuration for {symbol!r}.")
    if not math.isfinite(initial_balance) or initial_balance <= 0:
        raise ValueError("Initial balance must be positive and finite.")
    if symbol == "EURJPY" and QUOTE_TO_ACCOUNT_CURRENCY is None:
        raise ValueError("Set QUOTE_TO_ACCOUNT_CURRENCY to a JPY conversion rate for EURJPY.")
    conversion = QUOTE_TO_ACCOUNT_CURRENCY if QUOTE_TO_ACCOUNT_CURRENCY is not None else 1.0
    if not math.isfinite(conversion) or conversion <= 0:
        raise ValueError("QUOTE_TO_ACCOUNT_CURRENCY must be positive and finite.")
    use_m1_confirmation = use_m1_m5_confirmation and use_m1_confirmation
    use_m5_confirmation = use_m1_m5_confirmation and use_m5_confirmation
    if use_m1_confirmation and data_m1 is None:
        raise ValueError("M1 confirmation is enabled; provide data_m1.")
    if use_m5_confirmation and data_m5 is None:
        raise ValueError("M5 confirmation is enabled; provide data_m5.")
    blocked_slots = SYMBOL_BLOCKED_SLOTS_HKT[symbol]

    balance = initial_balance
    peak_balance = initial_balance
    max_drawdown = 0.0
    max_drawdown_pct = 0.0
    position: Optional[Dict] = None
    last_entry_slot = None
    trades: List[Dict] = []
    skipped_vp = 0
    skipped_blocked = 0
    skipped_min_lot = 0
    skipped_m1_m5 = 0
    skipped_m1_m5_data = 0

    df = pd.DataFrame(data)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    confirmation_data = {}
    for timeframe, enabled, records, minutes, lookback in (
        ("M1", use_m1_confirmation, data_m1, 1, 3),
        ("M5", use_m5_confirmation, data_m5, 5, 24),
    ):
        if not enabled:
            continue
        rates = _prepare_confirmation_rates(records, timeframe)
        if df["timestamp"].dt.tz != rates["timestamp"].dt.tz:
            raise ValueError(f"M15 and {timeframe} timestamps must use the same timezone.")
        close_times = pd.DatetimeIndex(rates["timestamp"] + pd.Timedelta(minutes=minutes))
        if len(close_times) < lookback:
            raise ValueError(f"{timeframe} history must contain at least {lookback} bars.")
        confirmation_data[timeframe] = (rates, close_times, minutes, lookback)

    if confirmation_data:
        confirmation_start = max(times[lookback - 1] for _, times, _, lookback in confirmation_data.values())
        confirmation_end = min(times[-1] for _, times, _, _ in confirmation_data.values())
        if confirmation_start > confirmation_end:
            raise ValueError("Enabled confirmation histories do not overlap.")
        print(
            f"{'/'.join(confirmation_data)} confirmation coverage: "
            f"{pd.Timestamp(confirmation_start)} to {pd.Timestamp(confirmation_end)}"
        )

    highs  = df["high"].values
    lows   = df["low"].values
    closes = df["close"].values
    opens  = df["open"].values
    timestamps = df["timestamp"]

    atrs   = calculate_atr(highs, lows, closes, window=14)
    sigmas = pd.Series(closes).rolling(20).std(ddof=0).values  # Exact live np.std parity
    skipped_hmm = 0
    if USE_HMM_FILTER:
        hmm_p_trend, hmm_p_spike = compute_causal_hmm_probs(closes, HMM_PARAMS_JSON)
    else:
        hmm_p_trend = np.ones(len(closes))
        hmm_p_spike = np.zeros(len(closes))

    start_i = max(VP_LOOKBACK_BARS, 50)

    print(f"Running backtest ({symbol}) on {len(df)} bars (start index {start_i})...")
    print(
        f"Assumptions: fixed spread {SPREAD}, contract size {CONTRACT_SIZE}, "
        f"quote conversion {conversion}; live spread, slippage and margin are not modeled."
    )

    for i in range(start_i, len(df) + 1):
        # ------------------------------------------------------------------
        # 1. Settle the prior candle before considering the next candle's open.
        # ------------------------------------------------------------------
        if i > start_i and position is not None:
            ts = timestamps.iloc[i - 1]
            high = highs[i - 1]
            low = lows[i - 1]
            bar_open = opens[i - 1]
            exit_price = None
            exit_reason = None

            if position["type"] == "BUY":
                if bar_open <= position["sl"]:
                    exit_price = bar_open
                    exit_reason = "LOSS"
                elif bar_open >= position["tp"]:
                    exit_price = position["tp"]
                    exit_reason = "WIN"
                elif low <= position["sl"]:
                    exit_price = position["sl"]
                    exit_reason = "LOSS"
                elif high >= position["tp"]:
                    exit_price = position["tp"]
                    exit_reason = "WIN"
            else:  # SELL
                ask_open = bar_open + SPREAD
                if ask_open >= position["sl"]:
                    exit_price = ask_open
                    exit_reason = "LOSS"
                elif ask_open <= position["tp"]:
                    exit_price = position["tp"]
                    exit_reason = "WIN"
                elif high + SPREAD >= position["sl"]:
                    exit_price = position["sl"]
                    exit_reason = "LOSS"
                elif low + SPREAD <= position["tp"]:
                    exit_price = position["tp"]
                    exit_reason = "WIN"

            if exit_price is not None:
                if position["type"] == "BUY":
                    gross = (exit_price - position["entry"]) * CONTRACT_SIZE * position["lot"] * conversion
                else:
                    gross = (position["entry"] - exit_price) * CONTRACT_SIZE * position["lot"] * conversion

                pnl = gross - (position["lot"] * COMMISSION_PER_LOT)
                r_mult = pnl / position["initial_risk"]

                balance += pnl
                peak_balance = max(peak_balance, balance)
                dd = peak_balance - balance
                dd_pct = (dd / peak_balance * 100.0) if peak_balance > 0 else 0.0
                max_drawdown = max(max_drawdown, dd)
                max_drawdown_pct = max(max_drawdown_pct, dd_pct)

                trades.append({
                    "type": position["type"],
                    "entry": position["entry"],
                    "exit": exit_price,
                    "pnl": pnl,
                    "r_mult": r_mult,
                    "lot": position["lot"],
                    "reason": exit_reason,
                    "entry_ts": position["entry_ts"],
                    "exit_ts": ts,
                    "duration": ts - position["entry_ts"],
                    "year": ts.year,
                })
                position = None
            elif MOVE_SL_TO_BE and not position["be_moved"]:
                if position["type"] == "BUY" and high >= position["entry"] + position["sl_dist"] * BE_TRIGGER_R:
                    position["sl"] = position["entry"] + SPREAD * 0.5
                    position["be_moved"] = True
                elif position["type"] == "SELL" and low + SPREAD <= position["entry"] - position["sl_dist"] * BE_TRIGGER_R:
                    position["sl"] = position["entry"] - SPREAD * 0.5
                    position["be_moved"] = True

        if balance <= 0:
            print(f"Trading stopped: balance exhausted (${balance:,.2f}).")
            break
        if i == len(df):
            break

        ts = timestamps.iloc[i]
        open_price = opens[i]

        # ------------------------------------------------------------------
        # 2. New entry logic (1 open trade per symbol, live slot filter)
        # ------------------------------------------------------------------
        if position is not None:
            continue

        if not is_scan_time(ts) or ts.floor("15min") == last_entry_slot:
            continue

        if is_blocked_slot(ts, blocked_slots):
            skipped_blocked += 1
            continue

        if USE_HMM_FILTER:
            active_regime_prob = hmm_p_trend[i - 1] + hmm_p_spike[i - 1]
            if active_regime_prob < HMM_TREND_THRESHOLD:
                skipped_hmm += 1
                continue

        lookback = closes[max(0, i - 144):i]
        if len(lookback) < 10:
            continue
        log_prices = np.log(lookback)
        drift = run_kalman_filter_2D(
            log_prices,
            process_noise=KALMAN_PROCESS_NOISE,
            measurement_noise=KALMAN_MEASURE_NOISE,
        )

        pre_drift = run_kalman_filter_2D(
            log_prices[:-1],
            process_noise=KALMAN_PROCESS_NOISE,
            measurement_noise=KALMAN_MEASURE_NOISE,
        )

        if drift > 0:
            signal = 1
        elif drift < 0:
            signal = -1
        else:
            continue

        atr_val = atrs[i - 1]
        sigma_val = sigmas[i - 1]
        if np.isnan(atr_val) or np.isnan(sigma_val) or atr_val <= 0:
            continue

        # Volume Profile filter
        if USE_VOLUME_PROFILE:
            window = df.iloc[i - VP_LOOKBACK_BARS:i]
            vah, val, _ = calculate_volume_profile(window)
            current_price = closes[i - 1]

            if signal == 1 and current_price <= vah:
                skipped_vp += 1
                continue
            if signal == -1 and current_price >= val:
                skipped_vp += 1
                continue

        if confirmation_data:
            if ts < confirmation_start or ts > confirmation_end:
                skipped_m1_m5_data += 1
                continue
            windows = {}
            for timeframe, (rates, close_times, minutes, lookback) in confirmation_data.items():
                count = close_times.searchsorted(ts, side="right")
                if count < lookback:
                    break
                window_times = close_times[count - lookback:count]
                if (window_times[-1] != ts or
                        not (window_times[1:] - window_times[:-1] == pd.Timedelta(minutes=minutes)).all()):
                    break
                windows[timeframe] = rates.iloc[count - lookback:count]
            if len(windows) != len(confirmation_data):
                skipped_m1_m5_data += 1
                continue
            if not confirm_m1_m5_entry(
                signal,
                atr_val,
                windows.get("M5"),
                windows.get("M1"),
            ):
                skipped_m1_m5 += 1
                continue

        # Position sizing
        sl_dist = max(atr_val, sigma_val * SD_MULTIPLIER)
        tp_dist = sl_dist * TARGET_RR_MULTIPLIER

        risk_cash = balance * RISK_PER_TRADE_PCT
        risk_per_lot = sl_dist * CONTRACT_SIZE * conversion
        lot_raw = risk_cash / risk_per_lot
        lot = min(MAX_ALLOWED_LOTS, max(0.01, math.floor(lot_raw * 100) / 100))
        actual_risk = risk_per_lot * lot
        if actual_risk > risk_cash * MIN_LOT_RISK_CAP_MULTIPLIER:
            skipped_min_lot += 1
            continue

        # Bid-based candles: buys enter at ask; sells enter at bid.
        if signal == 1:
            entry = open_price + SPREAD
            position = {
                "type": "BUY",
                "entry": entry,
                "sl": entry - sl_dist,
                "tp": entry + tp_dist,
                "lot": lot,
                "sl_dist": sl_dist,
                "initial_risk": actual_risk,
                "entry_ts": ts,
                "be_moved": False,
            }
        else:
            entry = open_price
            position = {
                "type": "SELL",
                "entry": entry,
                "sl": entry + sl_dist,
                "tp": entry - tp_dist,
                "lot": lot,
                "sl_dist": sl_dist,
                "initial_risk": actual_risk,
                "entry_ts": ts,
                "be_moved": False,
            }
        last_entry_slot = ts.floor("15min")

    # ----------------------------------------------------------------------
    # Reporting
    # ----------------------------------------------------------------------
    print_results(
        trades, symbol, initial_balance, balance,
        max_drawdown, max_drawdown_pct, skipped_vp, skipped_blocked,
        skipped_hmm, skipped_min_lot, skipped_m1_m5, skipped_m1_m5_data
    )
    print(f"Open positions at end: {int(position is not None)}")
    plot_equity_curve(trades, symbol, initial_balance)
    print_entry_slot_summary(trades)

    return {
        "trades": trades,
        "final_balance": balance,
        "max_drawdown": max_drawdown,
        "max_drawdown_pct": max_drawdown_pct,
        "skipped_vp": skipped_vp,
        "skipped_blocked": skipped_blocked,
        "skipped_hmm": skipped_hmm,
        "skipped_min_lot": skipped_min_lot,
        "skipped_m1_m5": skipped_m1_m5,
        "skipped_m1_m5_data": skipped_m1_m5_data,
        "open_position": position,
    }


def print_results(trades, symbol, initial_balance, final_balance,
                  max_dd, max_dd_pct, skipped_vp, skipped_blocked,
                  skipped_hmm, skipped_min_lot, skipped_m1_m5, skipped_m1_m5_data):
    if not trades:
        print("No trades taken.")
        print(f"Skipped by HMM regime     : {skipped_hmm}")
        print(f"Skipped by M1/M5 confirm  : {skipped_m1_m5}")
        print(f"Skipped: M1/M5 unavailable: {skipped_m1_m5_data}")
        return

    tdf = pd.DataFrame(trades)
    wins = tdf[tdf["reason"] == "WIN"]
    losses = tdf[tdf["reason"] == "LOSS"]
    total = len(tdf)
    win_rate = len(wins) / total * 100.0

    avg_win = wins["pnl"].mean() if not wins.empty else 0.0
    avg_loss = abs(losses["pnl"].mean()) if not losses.empty else 0.0
    rr = avg_win / avg_loss if avg_loss > 0 else 0.0
    total_pnl = tdf["pnl"].sum()
    total_r = tdf["r_mult"].sum()
    ev_r = tdf["r_mult"].mean()
    avg_dur = tdf["duration"].mean()

    # Max consecutive losses & Peak-to-Trough R Drawdown
    tdf["cum_r"] = tdf["r_mult"].cumsum()
    max_r_dd = (tdf["cum_r"].cummax() - tdf["cum_r"]).max()
    streaks = (tdf["reason"] == "LOSS").groupby((tdf["reason"] != "LOSS").cumsum()).sum()
    max_loss_streak = int(streaks.max()) if not streaks.empty else 0

    print(f"\n==================== BACKTEST RESULTS ({symbol}) ====================")
    print(f"Total trades executed     : {total}")
    print(f"Skipped by Volume Profile : {skipped_vp}")
    print(f"Skipped by blocked slots  : {skipped_blocked}")
    print(f"Skipped by HMM regime     : {skipped_hmm}")
    print(f"Skipped by min-lot cap    : {skipped_min_lot}")
    print(f"Skipped by M1/M5 confirm  : {skipped_m1_m5}")
    print(f"Skipped: M1/M5 unavailable: {skipped_m1_m5_data}")
    print(f"Winning trades            : {len(wins)} ({win_rate:.2f}%)")
    print(f"Losing trades             : {len(losses)}")
    print(f"Average win               : ${avg_win:,.2f}")
    print(f"Average loss              : -${avg_loss:,.2f}")
    print(f"Actual Risk:Reward        : 1 : {rr:.2f}")
    print(f"Expectancy (R / Trade)    : {ev_r:+.4f}R (Total: {total_r:+.1f}R)")
    print(f"Max Peak-to-Trough R DD   : -{max_r_dd:.1f}R (Max Loss Streak: {max_loss_streak})")
    print(f"Final balance             : ${final_balance:,.2f}")
    print(f"Net return                : {(final_balance / initial_balance - 1) * 100:,.2f}%")
    print(f"Max Drawdown (Peak-Trough): ${max_dd:,.2f} ({max_dd_pct:.2f}%)")
    print(f"Total net P&L             : ${total_pnl:,.2f}")
    print(f"Average trade duration    : {avg_dur}")
    print("--------------------------------------------------------------------")
    print("YEAR-BY-YEAR BREAKDOWN:")
    for yr, grp in tdf.groupby("year"):
        yr_wr = (grp["reason"] == "WIN").mean() * 100.0
        yr_r = grp["r_mult"].sum()
        yr_ev = grp["r_mult"].mean()
        print(f"  {yr}: {len(grp):4d} trades | WR: {yr_wr:5.2f}% | EV: {yr_ev:+.4f}R | Net: {yr_r:+7.1f}R")
    print("====================================================================")


def plot_equity_curve(trades, symbol, initial_balance, path="backtest_equity_curve.png"):
    if not trades:
        return
    timestamps = [pd.to_datetime(trades[0]["entry_ts"])] + [t["exit_ts"] for t in trades]
    pnls = [0.0] + [t["pnl"] for t in trades]
    equity = initial_balance + np.cumsum(pnls)

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(timestamps, equity, color="steelblue", linewidth=1.8)
    ax.axhline(initial_balance, color="black", ls="--", lw=0.8)
    ax.fill_between(timestamps, equity, initial_balance,
                    where=equity >= initial_balance, color="green", alpha=0.12)
    ax.fill_between(timestamps, equity, initial_balance,
                    where=equity < initial_balance, color="red", alpha=0.12)
    ax.set_title(f"Equity Curve ({symbol})")
    ax.set_xlabel("Time")
    ax.set_ylabel("Balance ($)")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"Equity curve saved -> {path}")


def print_entry_slot_summary(trades):
    if not trades:
        return
    df = pd.DataFrame(trades)
    df["entry_slot"] = pd.to_datetime(df["entry_ts"]).dt.strftime("%H:%M")
    summary = (
        df.groupby("entry_slot")
          .agg(total=("reason", "size"),
               wins=("reason", lambda x: (x == "WIN").sum()),
               losses=("reason", lambda x: (x == "LOSS").sum()))
          .reset_index()
    )
    summary["win_rate"] = summary["wins"] / summary["total"] * 100
    summary = summary.sort_values(["wins", "win_rate", "total"], ascending=False)

    print("\n-------------- Entry Slot Performance (15m) --------------")
    for _, row in summary.iterrows():
        print(f"{row['entry_slot']}  ->  "
              f"W:{int(row['wins']):3d}  L:{int(row['losses']):3d}  "
              f"Total:{int(row['total']):3d}  WR:{row['win_rate']:5.1f}%")
    print("----------------------------------------------------------")


# ==============================================================================
#                              MAIN
# ==============================================================================
if __name__ == "__main__":
    try:
        df = pd.read_csv("history_data.csv")
        data_m1 = (
            pd.read_csv(M1_HISTORY_CSV).to_dict("records")
            if USE_M1_M5_CONFIRMATION and USE_M1_CONFIRMATION else None
        )
        data_m5 = (
            pd.read_csv(M5_HISTORY_CSV).to_dict("records")
            if USE_M1_M5_CONFIRMATION and USE_M5_CONFIRMATION else None
        )
        data = df.to_dict("records")
        results = backtest_kalman(
            data,
            symbol=ACTIVE_SYMBOL,
            initial_balance=3000.0,
            data_m1=data_m1,
            data_m5=data_m5,
        )
    except FileNotFoundError as e:
        print(f"Error: required history file not found: {e.filename}")
    except Exception as e:
        print(f"Backtest failed: {e}")
        raise