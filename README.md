# QuantumGOLD-Nexus - Automated Gold Trading Bot

An automated gold trading bot based on EMA crossover strategy, supporting MetaTrader 5 platform with risk management and automatic stop-loss adjustment features.

## Features

### 🎯 Trading Strategy
- **EMA Crossover Strategy**: Uses 5-period and 15-period Exponential Moving Averages
- **ATR-based SL/TP**: Dynamic stop-loss and take-profit based on Average True Range
- **Automatic Position Management**: Moves stop-loss to breakeven when price reaches half of take-profit

### 📊 Risk Management
- **Per-trade Risk**: Configurable maximum loss percentage per trade
- **Daily Maximum Loss**: Fixed $500 or account balance percentage
- **Daily Maximum Profit**: Stops trading when daily profit target is reached
- **Dynamic Position Sizing**: Automatically calculates lot size based on risk and stop distance

### 🖥️ Real-time Monitoring
- **Graphical Interface**: Real-time display of trading status and account information
- **Multiple Monitoring Metrics**:
  - Today's P&L (Realized + Unrealized)
  - Account Balance
  - Current Position Status
  - Latest Trading Signal
  - Trade Count Statistics

## System Requirements

- Python 3.7+
- MetaTrader 5
- Required packages:
  ```
  MetaTrader5
  numpy
  tkinter (usually built-in)
  ```

## Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/DelsinC6806/StrategybasedBOT.git
   cd StrategybasedBOT
   ```

2. **Install dependencies**
   ```bash
   pip install MetaTrader5 numpy
   ```

3. **Ensure MT5 is installed and logged into your account**

## Usage

### Quick Start

```bash
python main.py
```

After startup, you'll be prompted to enter:
- Maximum loss percentage per trade (e.g., 0.01 = 1%)
- Trading company name
- Daily maximum loss percentage (e.g., 0.05 = 5%)

### Configuration Parameters

Adjustable parameters in main.py:

```python
symbol = "XAUUSD"           # Trading instrument
fast = 5                    # Fast EMA period
slow = 15                   # Slow EMA period
atr_mult_sl = 1.0          # ATR multiplier for stop-loss
atr_mult_tp = 4.0          # ATR multiplier for take-profit
contract_size = 100         # Contract size
daily_max_loss = 500        # Fixed daily maximum loss ($)
```

## Project Structure

```
StrategybasedBOT/
├── src/
│   ├── main.py           # Main program
│   ├── strategy.py       # Technical indicator calculations
│   └── placetrade.py     # Order execution functions
├── README.md
└── requirements.txt
```

## Trading Logic

### Entry Conditions
- **BUY Signal**: EMA(5) crosses above EMA(15) with no open position
- **SELL Signal**: EMA(5) crosses below EMA(15) with no open position

### Exit Management
- **Stop Loss**: Entry price ± ATR × 1.0
- **Take Profit**: Entry price ± ATR × 4.0
- **Trailing Stop**: Moves stop-loss to breakeven when price reaches half of take-profit

### Risk Control Mechanisms
1. **Per-trade Risk Control**:
   ```
   Lot Size = Risk Amount ÷ (Stop Distance × Contract Size)
   ```

2. **Daily Risk Control**:
   - Maximum loss reached → Pause trading
   - Maximum profit reached → Pause trading

## Time Settings

- **Trading Timeframe**: 15-minute candlesticks
- **Signal Check**: Every 15 minutes (triggered at exact intervals)
- **Position Monitoring**: Every second
- **Timezone Handling**: Automatic UTC time conversion

## Important Notes

### ⚠️ Risk Warning
- This software is for educational and research purposes only
- Automated trading involves risk of financial loss
- Test thoroughly on demo accounts before live trading
- Set reasonable risk parameters

### 🔧 Usage Recommendations
1. **First Use**: Recommended to test on demo accounts
2. **Parameter Adjustment**: Adjust ATR multipliers based on market conditions
3. **Monitor Operation**: Regularly check program running status
4. **Stable Network**: Ensure stable internet connection

## Troubleshooting

### Common Issues

1. **MT5 Initialization Failed**
   - Ensure MT5 is properly installed and logged in
   - Check if account allows automated trading

2. **Insufficient Candlestick Data**
   - Wait for market opening hours
   - Verify correct symbol code

3. **Order Placement Failed**
   - Check account balance is sufficient
   - Ensure stop-loss/take-profit distances meet broker requirements

## Code Issues Found

### Current Problems in main.py:

1. **Missing get_trade_count method in TradingBotUI class**:
   ```python
   # Line 173 - This will cause AttributeError
   self.trade_count_text.set(f"Trade Count: {self.get_trade_count()}")
   ```
   **Fix**: Remove `self.` and use the global function:
   ```python
   self.trade_count_text.set(f"Trade Count: {get_trade_count()}")
   ```

2. **today_pnl not being updated in main loop**:
   ```python
   # Line 184 - today_pnl is calculated once but never updated
   today_pnl = get_today_pnl()
   ```
   **Fix**: Move this inside the main loop to update continuously.

3. **Stop-loss breakeven logic issue**:
   The `move_sl_to_breakeven` function will trigger immediately instead of waiting for half TP, because the conditions `current_sl < entry_price` (for BUY) and `current_sl > entry_price` (for SELL) are always true for normal stop-loss positions.

### Recommended Fixes:

```python
def move_sl_to_breakeven(position):
    try:
        current_price = mt5.symbol_info_tick(symbol).last
        entry_price = position.price_open
        current_sl = position.sl
        current_tp = position.tp
        
        if position.type == mt5.POSITION_TYPE_BUY:
            half_tp_price = entry_price + (current_tp - entry_price) / 2
            # Add distance check to ensure SL hasn't been moved to breakeven yet
            if (current_price >= half_tp_price and 
                abs(current_sl - entry_price) > 0.5 and  # SL is still far from entry
                current_sl < entry_price):
                # Move to breakeven logic...
                
        elif position.type == mt5.POSITION_TYPE_SELL:
            half_tp_price = entry_price - (entry_price - current_tp) / 2
            if (current_price <= half_tp_price and 
                abs(current_sl - entry_price) > 0.5 and  # SL is still far from entry
                current_sl > entry_price):
                # Move to breakeven logic...
```

## Version History

### v1.0.0
- Basic EMA crossover strategy
- Risk management features
- Graphical monitoring interface
- Automatic stop-loss adjustment feature

## Contributing

Issues and Pull Requests are welcome to improve this project.

## License

This project is licensed under the MIT License.

---

**Disclaimer**: This software is for educational and research purposes only. Users must assume their own trading risks. The author is not responsible for any trading losses.