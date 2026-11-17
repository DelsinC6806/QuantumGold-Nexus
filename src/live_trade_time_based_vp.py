import math
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from backtest.backtest_time_based_vp import (
    calculate_atr,
    calculate_volume_profile,
    current_ts_is_scan_time,
    run_kalman_filter_2D,
)
from placetrade import place_trade, send_discord_notification

# ==============================================================================
# Live trading config based on the backtest strategy
# ==============================================================================
MAX_ALLOWED_SPREAD_PIPS = 16.0
MAX_SLIPPAGE_PIPS = 16.0
TARGET_RR_MULTIPLIER = 1.5
SD_MULTIPLIER = 0.7
VP_LOOKBACK_BARS = 96
VP_NUM_BINS = 50
KALMAN_PROCESS_NOISE = 1e-5
KALMAN_MEASURE_NOISE = 1e-3
HKT_TZ = ZoneInfo("Asia/Hong_Kong")

instances = [
    {
        "mt5_path": "C:/Program Files/MetaTrader 5/terminal64.exe",
        "instance_name": "FundingPips",
        "symbol": ["USTEC.x", "DJ30.x","US500.x"],
        "trading_company": "OANDA",
        "percentage_of_risk": 0.005,
        "trade_count": 0,
        "magic_number": 111111,
    }
]

notified_deals = set()

def check_recently_closed_trades(symbols, magic_number=None):
    now_utc = datetime.now(timezone.utc)
    from_time = now_utc - timedelta(hours=6)
    to_time = now_utc + timedelta(hours=6)

    deals = mt5.history_deals_get(from_time, to_time)
    if deals is None or len(deals) == 0:
        return

    for deal in deals:
        if deal.ticket in notified_deals:
            continue
        if deal.entry != mt5.DEAL_ENTRY_OUT or deal.symbol not in symbols:
            continue
        if magic_number is not None and deal.magic != magic_number:
            continue

        notified_deals.add(deal.ticket)
        profit = deal.profit + deal.swap + deal.commission
        deal_type = "BUY (Closed)" if deal.type == mt5.DEAL_TYPE_SELL else "SELL (Closed)"

        reason_str = "Manual / Bot Close"
        if deal.reason == mt5.DEAL_REASON_SL:
            reason_str = "🛑 Hit Stop Loss (SL)"
        elif deal.reason == mt5.DEAL_REASON_TP:
            reason_str = "🎯 Hit Take Profit (TP)"

        message = (
            f"📊 **Trade Closed Alert**\n"
            f"• Symbol: {deal.symbol}\n"
            f"• Type: {deal_type}\n"
            f"• Lots: {deal.volume}\n"
            f"• Net PnL: ${profit:.2f}\n"
            f"• Reason: {reason_str}\n"
            f"• Time: {datetime.fromtimestamp(deal.time, tz=timezone.utc).astimezone(HKT_TZ).strftime('%Y-%m-%d %H:%M:%S HKT')}"
        )
        send_discord_notification(message)


def get_current_holding(symbol):
    positions = mt5.positions_get(symbol=symbol)
    if positions and len(positions) > 0:
        pos_type = positions[0].type
        if pos_type == mt5.POSITION_TYPE_BUY:
            return "BUY"
        if pos_type == mt5.POSITION_TYPE_SELL:
            return "SELL"
    return "None"


def round_to_step(volume, step):
    if step <= 0:
        return round(volume, 2)
    return math.floor(volume / step) * step


def close_all_positions(symbols, trading_company):
    for symbol in symbols:
        positions = mt5.positions_get(symbol=symbol) or []
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            continue

        for pos in positions:
            vol = pos.volume
            if vol <= 0:
                continue
            if pos.type == mt5.POSITION_TYPE_BUY:
                place_trade(symbol, "SELL", vol, 0, 0, tick.bid, trading_company)
            elif pos.type == mt5.POSITION_TYPE_SELL:
                place_trade(symbol, "BUY", vol, 0, 0, tick.ask, trading_company)


def strategy_signal_for_symbol(symbol):
    rates_m15 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 1, 250)
    if rates_m15 is None or len(rates_m15) < VP_LOOKBACK_BARS:
        return 0, None, None

    rates_df = pd.DataFrame(rates_m15)
    closes = rates_df["close"].to_numpy(dtype=float)
    current_price = closes[-1]

    kalman_lookback = closes[max(0, len(closes) - 48) :]
    if len(kalman_lookback) < 3:
        return 0, None, None
    
    kalman_lookback_log = np.log(kalman_lookback)
    drift_prev = run_kalman_filter_2D(
        kalman_lookback_log[:-1],
        process_noise=KALMAN_PROCESS_NOISE,
        measurement_noise=KALMAN_MEASURE_NOISE,
    )

    drift = run_kalman_filter_2D(
        np.log(kalman_lookback),
        process_noise=KALMAN_PROCESS_NOISE,
        measurement_noise=KALMAN_MEASURE_NOISE,
    )

    signal = 0
    if drift > 0:
        signal = 1
    elif drift < 0:
        signal = -1

    if signal == 0:
        return 0, None, None

    vp_window = rates_df.iloc[-VP_LOOKBACK_BARS:]
    vah, val, _ = calculate_volume_profile(vp_window, num_bins=VP_NUM_BINS)

    if signal == 1 and current_price <= vah:
        return 0, None, None
    if signal == -1 and current_price >= val:
        return 0, None, None

    highs = rates_df["high"].to_numpy(dtype=float)
    lows = rates_df["low"].to_numpy(dtype=float)
    atr_val = calculate_atr(highs, lows, closes, window=14)[-1]
    sigma_val = np.std(closes[-20:])

    if not np.isfinite(atr_val) or not np.isfinite(sigma_val):
        return 0, None, None

    sl_dist = max(float(atr_val), float(sigma_val) * SD_MULTIPLIER)
    tp_dist = sl_dist * TARGET_RR_MULTIPLIER
    return signal, sl_dist, tp_dist


def signal_Granted(instance, symbol, signal, tp_dist, sl_dist, requested_price):
    tick = mt5.symbol_info_tick(symbol)
    symbol_info = mt5.symbol_info(symbol)
    if tick is None or symbol_info is None:
        print(f"[{instance['instance_name']}] Failed to retrieve tick/symbol info for {symbol}")
        return

    point = symbol_info.point
    digits = symbol_info.digits
    current_market_price = tick.ask if signal == 1 else tick.bid
    price_diff_pips = abs(current_market_price - requested_price) / (point * 10)

    if price_diff_pips > MAX_SLIPPAGE_PIPS:
        print(f"[{instance['instance_name']}] SKIP {symbol}: Slippage too high! ({price_diff_pips:.1f} pips > {MAX_SLIPPAGE_PIPS} pips)")
        return

    account_info = mt5.account_info()
    if account_info is None or not account_info.trade_allowed:
        print(f"{instance['instance_name']}: Trade permission denied")
        return

    balance = account_info.balance
    risk_amount = balance * instance["percentage_of_risk"]

    tick_size = symbol_info.trade_tick_size
    tick_value = symbol_info.trade_tick_value
    sl_in_ticks = sl_dist / tick_size if tick_size > 0 else 0

    if sl_in_ticks > 0 and tick_value > 0:
        lot_raw = risk_amount / (sl_in_ticks * tick_value)
    else:
        lot_raw = symbol_info.volume_min

    lot = round_to_step(lot_raw, symbol_info.volume_step)
    lot = max(symbol_info.volume_min, min(symbol_info.volume_max, lot))
    lot = round(lot, 2)

    if signal == 1:
        entry_price = tick.ask
        sl = round(entry_price - sl_dist, digits)
        tp = round(entry_price + tp_dist, digits)
        print(f"[{instance['instance_name']}] Executing BUY {symbol} | Risk: ${risk_amount:.2f} | Lot: {lot:.2f} | SL: {sl} | TP: {tp}")
        place_trade(symbol, "BUY", lot, sl, tp, entry_price, instance["trading_company"])
    elif signal == -1:
        entry_price = tick.bid
        sl = round(entry_price + sl_dist, digits)
        tp = round(entry_price - tp_dist, digits)
        print(f"[{instance['instance_name']}] Executing SELL {symbol} | Risk: ${risk_amount:.2f} | Lot: {lot:.2f} | SL: {sl} | TP: {tp}")
        place_trade(symbol, "SELL", lot, sl, tp, entry_price, instance["trading_company"])

def trading_loop(instances):
    master = instances[0]

    if not mt5.initialize(path=master["mt5_path"]):
        print(f"initialize() failed for {master['instance_name']}")
        return

    init_deals = mt5.history_deals_get(
        datetime.now(timezone.utc) - timedelta(hours=12),
        datetime.now(timezone.utc) + timedelta(hours=6),
    )
    if init_deals:
        for d in init_deals:
            notified_deals.add(d.ticket)

    last_scan_key = None
    last_deal_check = 0.0

    while True:
        now_hkt = datetime.now(HKT_TZ)
        now_mono = time.monotonic()

        if now_mono - last_deal_check >= 5.0:
            last_deal_check = now_mono
            check_recently_closed_trades(master["symbol"])

        if now_hkt.second < 10:
            scan_key = now_hkt.strftime("%Y-%m-%d %H:%M")
            is_scan_time = current_ts_is_scan_time(now_hkt, start_hour=0, end_hour=23, interval_minutes=15)

            if is_scan_time and scan_key != last_scan_key:
                last_scan_key = scan_key
                current_slot_hkt = now_hkt.strftime("%H:%M")
                if mt5.terminal_info() is None and not mt5.initialize(path=master["mt5_path"]):
                    print(f"Re-initializing MT5 failed for {master['instance_name']}")
                    time.sleep(1)
                    continue

                if now_hkt.hour == 4 and now_hkt.minute == 45:
                    # close_all_positions(master["symbol"], master["trading_company"])
                    time.sleep(1)
                    continue

                print(f"Triggering 15-minute scan for {scan_key} HKT")

                for idx, symbol in enumerate(master["symbol"]):
                    current_slot_hkt = now_hkt.strftime("%H:%M")
                    if current_slot_hkt in SYMBOL_BLOCKED_SLOTS_HKT.get(symbol, set()):
                        continue

                    if get_current_holding(symbol) != "None":
                        continue

                    symbol_info = mt5.symbol_info(symbol)
                    tick = mt5.symbol_info_tick(symbol)
                    if symbol_info is None or tick is None:
                        continue

                    spread_pips = (tick.ask - tick.bid) / (symbol_info.point * 10)
                    if spread_pips > MAX_ALLOWED_SPREAD_PIPS:
                        print(f"SKIP {symbol}: Spread too wide ({spread_pips:.1f} pips > {MAX_ALLOWED_SPREAD_PIPS} pips)")
                        continue

                    signal, sl_dist, tp_dist = strategy_signal_for_symbol(symbol)
                    if signal == 0 or sl_dist is None or tp_dist is None:
                        continue

                    target_tick = mt5.symbol_info_tick(symbol)
                    if target_tick is None:
                        continue
                    req_price = target_tick.ask if signal == 1 else target_tick.bid

                    for instance in instances:
                        signal_Granted(
                            instance,
                            instance["symbol"][idx % len(instance["symbol"])],
                            signal,
                            tp_dist,
                            sl_dist,
                            req_price,
                        )

            elif not is_scan_time:
                last_scan_key = None

        time.sleep(0.5)


if __name__ == "__main__":
    send_discord_notification(f"🚀 **Live VP Kalman Trading Bot Started** {datetime.now(HKT_TZ).strftime('%Y-%m-%d %H:%M:%S HKT')}")
    trading_loop(instances)
