# QuantumGold-Nexus

QuantumGold-Nexus is a Python-based MetaTrader 5 (MT5) trading and research
repository. It contains live-trading scripts, reusable indicator and order
helpers, and a collection of historical-data backtests. It is not a packaged
desktop application, and the scripts do not all share one configuration or
strategy.

> **Financial risk:** Automated trading can lose money, including more than
> expected due to leverage, gaps, spread, slippage, broker rules, or software
> failures. This project is provided for research and educational use only. It
> is not financial advice or a promise of performance. Use a demo account first
> and independently verify every strategy and risk setting before any live use.

## What is in this repository?

| Location | Purpose |
| --- | --- |
| `src/main.py` | EMA-based, multi-symbol MT5 strategy using H1 trend context and M15 signals. |
| `src/live_trade_time_based_vp.py` | Time-based Kalman/volume-profile live strategy. This file currently contains unresolved merge-conflict markers; do not run it until they are resolved and the script is reviewed. |
| `src/live_trade_kalman_vp_highrisk.py` | Alternative time-based Kalman/volume-profile live strategy. Its trading parameters and symbols are defined in the source. |
| `src/simple.py` | Another standalone live-trading script. |
| `src/strategy.py` | EMA, ATR, RSI, Fibonacci, and related indicator helpers. |
| `src/placetrade.py` | MT5 order submission, trade logging, and optional Discord notifications. |
| `src/config_loader.py` | INI configuration helper; the live scripts do not all use it. |
| `src/backtest/` | Experimental and alternative historical backtest implementations. |
| `src/extractData.py` | MT5 historical-data export script. It currently contains unresolved merge-conflict markers; do not run it until they are resolved and the script is reviewed. |
| `src/trainHMM.py` | HMM regime-model training and evaluation utilities. |
| `tests/` | Focused automated tests for selected backtest and shutdown behavior. |

The scripts are independent experiments, not interchangeable entry points.
Review the selected script and its settings before starting it.

## Requirements

- Windows with a working MetaTrader 5 terminal and an account you are
  authorized to use. The Python MT5 integration communicates with the local
  terminal.
- A compatible 64-bit Python installation.
- The Python dependencies listed in [`requirements.txt`](requirements.txt).

## Setup

From the repository root, create and activate a virtual environment in
PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Install the requirements in the same Python environment that will run the
script. If installation fails, check that your Python version and platform are
compatible with the pinned packages.

Before attempting live trading:

1. Install and open the MT5 terminal; sign in to the intended **demo** account.
2. Confirm the broker's symbol names and that the required market data is
   available.
3. Open the selected script and verify its terminal path, symbols, broker name,
   risk fraction, signal schedule, and order settings. These are currently
   defined in source for the live scripts.
4. Enable algorithmic trading only when you are ready to test. Broker-side
   permissions, symbol settings, and market hours can affect execution.
5. To receive Discord trade alerts, set `DISCORD_WEBHOOK_URL` in the
   environment before launching the script. It is optional; do not commit
   webhook URLs, account passwords, or other credentials to the repository.

The repository does not currently provide a maintained Docker deployment
configuration or a shared command-line configuration workflow.

## Run a live script

For the EMA-based script, run it from `src` so its local imports resolve:

```powershell
Set-Location .\src
python .\main.py
```

The script contains its own MT5 terminal path, symbols, and risk settings.
Inspect and adjust those values for your environment before running it. Other
live strategies are separate scripts and may use different symbols, schedules,
and risk controls. Do not assume the settings in one apply to another.

Stop the process with `Ctrl+C`. Live trading can place real orders; verify the
account and mode in the MT5 terminal before launching.

## Backtesting and historical data

Backtests are individual research scripts, with different assumptions and
input formats. Check the selected file's top-level parameters and its `__main__`
block for expected inputs and outputs. Some scripts expect a local
`history_data.csv` in the current working directory; this file is not tracked
as project source. The root `.gitignore` excludes CSV data, model artifacts,
and generated charts.

For example, the volume-profile/Kalman backtest reads `history_data.csv` from
the current directory:

```powershell
python .\src\backtest\backtest_time_based_vp.py
```

Provide data in the format expected by that script. The MT5 data-export script
is currently blocked by unresolved merge conflicts, so obtain or prepare data
separately until that file is repaired.

Backtest results are sensitive to data quality, timezone handling, spread,
slippage, commission, and modeling assumptions. Historical results do not
predict future performance.

## Tests

Install `pytest` in the active environment if it is not already available, then
run the test suite from the repository root:

```powershell
python -m pytest
```

The current tests cover only selected behaviors; a passing test run does not
validate trading performance, broker compatibility, or live execution.

## Configuration and logs

- `src/main.py` and the live strategy scripts define their trading instances
  and parameters directly in Python.
- `src/config_loader.py` can read an optional `config.ini`, but it is not a
  universal configuration layer for the scripts.
- `src/placetrade.py` reads the optional `DISCORD_WEBHOOK_URL` environment
  variable and appends successful order details to `trade_log.txt` in the
  process's current working directory.
- Keep credentials and webhook URLs out of source control. The repository
  ignores `.ini` files and local trading data.

## Known repository limitations

- `src/live_trade_time_based_vp.py` and `src/extractData.py` contain unresolved
  merge-conflict markers and require repair before use.
- Live trading scripts have separate, source-defined settings; there is no
  single supported launcher or unified configuration interface.
- Backtest scripts are experimental and may have different data schemas,
  assumptions, and output formats.
- Docker-related notes and deployment-test code in the repository are not a
  maintained deployment path.

Review the exact code you intend to run, test changes on historical data and a
demo account, and confirm broker behavior before considering any live
deployment.
