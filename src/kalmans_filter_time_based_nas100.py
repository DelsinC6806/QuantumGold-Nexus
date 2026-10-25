import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import time
import numpy as np
import math
import os
import pandas as pd
from placetrade import place_trade, send_discord_notification

# ==============================================================================
#                      CONFIG & FRICTION CONTROLS
# ==============================================================================
MAX_ALLOWED_SPREAD_PIPS = 20.0  # Reject entries if spread > 2.0 pips
MAX_SLIPPAGE_PIPS = 20.0        # Reject entries if price slips > 2.0 pips
ATR_MULT_SL = 0.7
TARGET_RR_MULTIPLIER = 1.5

VP_LOOKBACK_BARS = 96
VP_TARGET_VOL_PCT = 0.68
VP_NUM_BINS = 50

HKT_TZ = ZoneInfo("Asia/Hong_Kong")

instances = [
    {                                                                        
        'mt5_path': 'C:/Program Files/MetaTrader 5/terminal64.exe',
        'instance_name': 'FundingPips',
        'symbol': ['USTEC.x','US500.x'],
        'trading_company': 'OANDA',
        'percentage_of_risk': 0.0075,
        'trade_count': 0,
        'magic_number': 111111
    },
]

# ==============================================================================
#                      MATH & ANALYTICS HELPERS
# ==============================================================================
def calculate_atr(rates_m15, window=14):
    highs = np.array([x['high'] for x in rates_m15])
    lows = np.array([x['low'] for x in rates_m15])
    closes = np.array([x['close'] for x in rates_m15])
    
    tr1 = highs - lows
    tr2 = np.zeros(len(closes))
    tr3 = np.zeros(len(closes))
    tr2[1:] = np.abs(highs[1:] - closes[:-1])
    tr3[1:] = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    return pd.Series(tr).rolling(window=window).mean().values

def calculate_volume_profile(rates_slice, num_bins=VP_NUM_BINS):
    lows = np.array([x['low'] for x in rates_slice])
    highs = np.array([x['high'] for x in rates_slice])
    closes = np.array([x['close'] for x in rates_slice])
    vols = np.array([x['tick_volume'] for x in rates_slice])
    
    price_min = np.min(lows)
    price_max = np.max(highs)
    
    if price_max == price_min:
        return closes[-1], closes[-1], closes[-1]
        
    bins = np.linspace(price_min, price_max, num_bins + 1)
    bin_indices = np.clip(np.digitize(closes, bins) - 1, 0, num_bins - 1)
    
    bin_volumes = np.zeros(num_bins)
    for idx, vol in zip(bin_indices, vols):
        bin_volumes[idx] += vol
        
    poc_idx = np.argmax(bin_volumes)
    poc = (bins[poc_idx] + bins[poc_idx + 1]) / 2.0
    
    total_vol = np.sum(bin_volumes)
    target_vol = total_vol * VP_TARGET_VOL_PCT  
    
    sorted_bin_indices = np.argsort(bin_volumes)[::-1]
    cum_vol = 0
    selected_bins = []
    
    for idx in sorted_bin_indices:
        cum_vol += bin_volumes[idx]
        selected_bins.append(idx)
        if cum_vol >= target_vol:
            break
            
    val = bins[min(selected_bins)]
    vah = bins[max(selected_bins) + 1]
    
    return vah, val, poc

def run_kalman_filter_drift(closes_slice, process_noise=1e-5, measurement_noise=1e-3):
    F = np.array([[1.0, 1.0],
                  [0.0, 1.0]])
    H = np.array([[1.0, 0.0]])
    
    Q = np.eye(2) * process_noise
    R = np.array([[measurement_noise]])
    
    x = np.array([[closes_slice[0]], [0.0]])
    P = np.eye(2) * 1.0
    
    for z in closes_slice:
        x = F @ x
        P = F @ P @ F.T + Q
        
        y = z - (H @ x)[0, 0]
        S = H @ P @ H.T + R
        K = P @ H.T / S[0, 0]
        
        x = x + K * y
        P = (np.eye(2) - K @ H) @ P
        
    return x[1, 0]

def round_to_step(volume, step):
    if step <= 0:
        return round(volume, 2)
    return math.floor(volume / step) * step

# ==============================================================================
#                      MT5 EXECUTION ENGINE
# ==============================================================================
def check_recently_closed_trades(symbol, last_check_time):
    now_utc = datetime.now(timezone.utc)
    deals = mt5.history_deals_get(last_check_time, now_utc, group=symbol)

    if deals is None or len(deals) == 0:
        return

    for deal in deals:
        if deal.entry == 1: 
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
        elif pos_type == mt5.POSITION_TYPE_SELL:
            return "SELL"
    return "None"

def close_all_positions(symbol, trading_company):
    positions = mt5.positions_get(symbol=symbol) or []
    tick = mt5.symbol_info_tick(symbol)
    for pos in positions:
        vol = pos.volume
        if vol <= 0:
            continue
        if pos.type == mt5.POSITION_TYPE_BUY:
            place_trade(symbol, "SELL", vol, 0, 0, tick.bid, trading_company)
        elif pos.type == mt5.POSITION_TYPE_SELL:
            place_trade(symbol, "BUY", vol, 0, 0, tick.ask, trading_company)

def signal_Granted(instance, symbol, signal, tp_dist, sl_dist, requested_price):
    if not mt5.initialize(path=instance['mt5_path']):
        print(f"initialize() failed for {instance['instance_name']}")
        return
    
    tick = mt5.symbol_info_tick(symbol)
    symbol_info = mt5.symbol_info(symbol)
    if tick is None or symbol_info is None:
        print(f"[{instance['instance_name']}] Failed to retrieve tick/symbol info")
        return

    point = symbol_info.point
    current_market_price = tick.ask if signal == 1 else tick.bid
    price_diff_pips = abs(current_market_price - requested_price) / (point * 10)
    
    if price_diff_pips > MAX_SLIPPAGE_PIPS:
        print(f"[{instance['instance_name']}] SKIP: Slippage too high! ({price_diff_pips:.1f} pips > {MAX_SLIPPAGE_PIPS} pips)")
        return

    account_info = mt5.account_info()
    if account_info is None or not account_info.trade_allowed:
        print(f"{instance['instance_name']}: Trade permission denied")
        return
    
    balance = account_info.balance
    risk_amount = balance * instance['percentage_of_risk']

    tick_size = symbol_info.trade_tick_size
    tick_value = symbol_info.trade_tick_value

    sl_in_ticks = sl_dist / tick_size

    if sl_in_ticks > 0 and tick_value > 0:
        lot_raw = risk_amount / (sl_in_ticks * tick_value)
    else:
        lot_raw = symbol_info.volume_min

    lot = round_to_step(lot_raw, symbol_info.volume_step)
    lot = max(symbol_info.volume_min, min(symbol_info.volume_max, lot))
    lot = round(lot, 2)

    if signal == 1:  # BUY
        entry_price = tick.ask
        sl = round(entry_price - sl_dist, 2)
        tp = round(entry_price + tp_dist, 2)
        print(f"[{instance['instance_name']}] Executing BUY | Risk: ${risk_amount:.2f} | Lot: {lot:.2f} | SL: {sl:.2f} | TP: {tp:.2f}")
        place_trade(symbol, "BUY", lot, sl, tp, entry_price, instance['trading_company'])
        
    elif signal == -1:  # SELL
        entry_price = tick.bid
        sl = round(entry_price + sl_dist, 2)
        tp = round(entry_price - tp_dist, 2)
        print(f"[{instance['instance_name']}] Executing SELL | Risk: ${risk_amount:.2f} | Lot: {lot:.2f} | SL: {sl:.2f} | TP: {tp:.2f}")
        place_trade(symbol, "SELL", lot, sl, tp, entry_price, instance['trading_company'])

# ==============================================================================
#                      MAIN TRADING LOOP
# ==============================================================================
def trading_loop(instances):
    master = instances[0]

    if not mt5.initialize(path=master['mt5_path']):
        print(f"initialize() failed for {master['instance_name']}")
        return
    
    last_history_check = datetime.now(timezone.utc) - timedelta(seconds=10)
    
    while True:
        now_hkt = datetime.now(HKT_TZ)

        # Check for closed trades every 5 seconds
        if now_hkt.second % 5 == 0:
            for symbol in master['symbol']:
                check_recently_closed_trades(symbol, last_history_check)
            last_history_check = datetime.now(timezone.utc)
            
        # Re-initialize MT5 context every minute
        if now_hkt.second == 0:
            if not mt5.initialize(path=master['mt5_path']):
                print(f"Re-initializing MT5 failed for {master['instance_name']}")
                time.sleep(1)
                continue

            position = get_current_holding(master['symbol'][0])


            # =================================================================
            # STRATEGY TRIGGER AT 20:00 HKT
            # =================================================================
            if now_hkt.hour == 20 and now_hkt.minute == 0:
                print(f"Triggering execution routine for {now_hkt.strftime('%Y-%m-%d')} at 20:00 HKT")
                
                for i, symbol in enumerate(master['symbol']):
                    symbol_info = mt5.symbol_info(symbol)
                    if symbol_info is None:
                        continue
                    
                    point = symbol_info.point
                    spread_ok = False
                    start_time = time.time()
                    
                    # Spread validation retry loop (up to 300s)
                    while time.time() - start_time < 300:
                        tick = mt5.symbol_info_tick(symbol)
                        if tick is not None:
                            spread_pips = (tick.ask - tick.bid) / (point * 10)
                            if spread_pips <= MAX_ALLOWED_SPREAD_PIPS:
                                print(f"Spread acceptable ({spread_pips:.1f} pips). Proceeding...")
                                spread_ok = True
                                break
                            else:
                                print(f"Spread wide ({spread_pips:.1f} pips). Retrying...")
                        time.sleep(1)
                    
                    if not spread_ok:
                        print(f"SKIP EXECUTION: Spread did not normalize within 300s.")
                        continue

                    # Fetch M15 historical bars
                    rates_m15 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M15, 1, 250)
                    if rates_m15 is None or len(rates_m15) < VP_LOOKBACK_BARS:
                        print("Insufficient M15 rates fetched.")
                        continue

                    closes = np.array([x['close'] for x in rates_m15])
                    current_price = closes[-1]

                    # 1. Kalman Filter Drift Calculation
                    kalman_lookback = closes[-48:]
                    kalman_lookback_log = np.log(kalman_lookback)
                    drift = run_kalman_filter_drift(kalman_lookback_log, process_noise=1e-5, measurement_noise=1e-3)
                    
                    signal = 0
                    if drift > 0:
                        signal = 1
                    elif drift < 0:
                        signal = -1

                    # 2. Volume Profile Value Area Filter (68% Value Area)
                    vp_window = rates_m15[-VP_LOOKBACK_BARS:]
                    vah, val, _ = calculate_volume_profile(vp_window, num_bins=VP_NUM_BINS)

                    # Gatekeeper: Filter out entries stuck inside Value Area
                    if signal == 1 and current_price <= vah:
                        send_discord_notification(f"{symbol} SKIP: BUY signal but price ({current_price:.2f}) <= VAH ({vah:.2f})")
                        continue
                    elif signal == -1 and current_price >= val:
                        send_discord_notification(f"{symbol} SKIP: SELL signal but price ({current_price:.2f}) >= VAL ({val:.2f})")
                        continue

                    # 3. Volatility Distance Calculations
                    atr14_val = calculate_atr(rates_m15, 14)[-1]
                    atr_sl = atr14_val * ATR_MULT_SL
                    
                    sigma = np.std(closes[-20:])
                    sd_sl = sigma * ATR_MULT_SL
                    
                    sl_dist = max(atr_sl, sd_sl)
                    tp_dist = sl_dist * TARGET_RR_MULTIPLIER

                    target_tick = mt5.symbol_info_tick(symbol)
                    req_price = target_tick.ask if signal == 1 else target_tick.bid

                    for instance in instances:
                        signal_Granted(instance, instance['symbol'][i], signal, tp_dist, sl_dist, req_price)
                
                time.sleep(60)
                continue

        time.sleep(1)

if __name__ == "__main__":
    send_discord_notification(f"🚀 **ROG ALLY Trading Bot Started** {datetime.now(HKT_TZ).strftime('%Y-%m-%d %H:%M:%S HKT')}")
    trading_loop(instances)