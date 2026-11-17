import requests
import time
import configparser

# Load Discord webhook from config.ini
config = configparser.ConfigParser()
config.read('/app/config.ini')

DISCORD_WEBHOOK_URL = config.get('discord', 'webhook_url', fallback='')

def send_discord_notification(message):
    """Helper function to send messages to Discord channel."""
    if not DISCORD_WEBHOOK_URL or "YOUR_WEBHOOK" in DISCORD_WEBHOOK_URL or "[REDACTED]" in DISCORD_WEBHOOK_URL:
        print(f"[Discord Skipped] {message[:50]}...")
        return

    payload = {"content": message}
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if response.status_code != 204:
            print(f"Discord alert failed with status code: {response.status_code}")
    except Exception as e:
        print(f"Failed to send Discord notification: {e}")

def place_trade(mt5, symbol, action, lot_size, sl_price, tp_price, price, trading_company):
    """Place a trade on MetaTrader 5 via mt5linux and send Discord alerts."""
    # Define the trade action
    if action.lower() == "buy":
        trade_type = mt5.ORDER_TYPE_BUY
    elif action.lower() == "sell":
        trade_type = mt5.ORDER_TYPE_SELL
    else:
        error_msg = f"❌ **Trade Blocked:** Invalid trade action received: '{action}'"
        print(error_msg)
        send_discord_notification(error_msg)
        return False

    if trading_company.lower() == "oanda":
        trade_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot_size,
            "type": trade_type,
            "price": price,
            "sl": sl_price,
            "tp": tp_price,
            "deviation": 10,
            "magic": 123456,
            "comment": "Strategy-based trade",
            "type_time": mt5.ORDER_TIME_GTC,
        }
    else:
        trade_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot_size,
            "type": trade_type,
            "price": price,
            "sl": sl_price,
            "tp": tp_price,
            "deviation": 10,
            "magic": 123456,
            "comment": "Strategy-based trade",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

    print("Trade Request:", trade_request)

    if not mt5.symbol_select(symbol, True):
        error_msg = f"❌ **MT5 Error:** Failed to select symbol: `{symbol}`"
        print(error_msg)
        send_discord_notification(error_msg)
        return False

    # Send the trade request
    result = mt5.order_send(trade_request)
    if result is None:
        error_msg = f"🚨 **Execution Failed:** `mt5.order_send()` returned None for `{symbol}`.\nError details: {mt5.last_error()}"
        print(error_msg)
        send_discord_notification(error_msg)
        return False

    # Check the result
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        error_msg = (
            f"❌ **Trade Rejected!**\n"
            f"• **Symbol:** `{symbol}`\n"
            f"• **Return Code:** `{result.retcode}`\n"
            f"• **Comment:** `{result.comment}`"
        )
        print(f"Trade failed: {result.retcode}")
        print("Trade result details:", result)
        send_discord_notification(error_msg)
        return False

    # Log the trade details to a file
    log_trade(symbol, action, lot_size, sl_price, tp_price, result.price)

    # Success notification via Discord
    success_msg = (
        f"✅ **Trade Executed Successfully!**\n"
        f"• **Action:** `{action.upper()}`\n"
        f"• **Symbol:** `{symbol}`\n"
        f"• **Lots:** `{lot_size}`\n"
        f"• **Executed Price:** `{result.price}`\n"
        f"• **Stop Loss:** `{sl_price}`\n"
        f"• **Take Profit:** `{tp_price}`"
    )
    print(f"Trade successful: {action.upper()} {lot_size} lots of {symbol}")
    send_discord_notification(success_msg)

    return True

def log_trade(symbol, action, lot_size, sl_price, tp_price, executed_price):
    """Log the trade details to a text file."""
    log_entry = (
        f"Trade Executed:\n"
        f"Symbol: {symbol}\n"
        f"Action: {action.upper()}\n"
        f"Lot Size: {lot_size}\n"
        f"Executed Price: {executed_price}\n"
        f"Stop-Loss: {sl_price}\n"
        f"Take-Profit: {tp_price}\n"
        f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"{'-' * 40}\n"
    )

    with open("/app/trade_log.txt", "a") as log_file:
        log_file.write(log_entry)
