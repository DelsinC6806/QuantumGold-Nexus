import MetaTrader5 as mt5
import time


def place_trade(symbol, action, lot_size, sl_price, tp_price,price, trading_company):
    """
    Place a trade on MetaTrader 5.

    Args:
        symbol (str): The trading symbol (e.g., "XAUUSD").
        action (str): "buy" or "sell".
        lot_size (float): The lot size for the trade.
        sl_price (float): Stop-loss price.
        tp_price (float): Take-profit price.

    Returns:
        bool: True if the trade was successful, False otherwise.
    """
    # Define the trade action
    if action.lower() == "buy":
        trade_type = mt5.ORDER_TYPE_BUY
    elif action.lower() == "sell":
        trade_type = mt5.ORDER_TYPE_SELL
    else:
        print("Invalid trade action")
        return False

    
    if trading_company == "OANDA":
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
    else :
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
            "type_filling": mt5.ORDER_FILLING_IOC,  # Immediate or Cancel filling
        }


    # Print the trade request for debugging
    print("Trade Request:", trade_request)

    if not mt5.initialize():
        print("MetaTrader 5 initialization failed")
        print(mt5.last_error())

    if not mt5.symbol_select(symbol, True):
        print(f"Failed to select symbol: {symbol}")
        return False

    # Send the trade request
    result = mt5.order_send(trade_request)
    if result is None:
        print("Trade request failed: mt5.order_send() returned None")
        print("Error details:", mt5.last_error())
        return False

    # Check the result
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Trade failed: {result.retcode}")
        print("Trade result details:", result)
        return False

        # Log the trade details to a file
    log_trade(symbol, action, lot_size, sl_price, tp_price, result.price)

    print(f"Trade successful: {action.upper()} {lot_size} lots of {symbol}")
    return True

def log_trade(symbol, action, lot_size, sl_price, tp_price, executed_price):
    """
    Log the trade details to a text file.

    Args:
        symbol (str): The trading symbol.
        action (str): "buy" or "sell".
        lot_size (float): The lot size for the trade.
        sl_price (float): Stop-loss price.
        tp_price (float): Take-profit price.
        executed_price (float): The price at which the trade was executed.
    """
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

    # Append the log entry to a file
    with open("trade_log.txt", "a") as log_file:
        log_file.write(log_entry)