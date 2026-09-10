# MT5 Login Verification Guide

## Overview
QuantumGold-Nexus includes a comprehensive login verification system to ensure the bot has successfully authenticated to your MT5 account before trading.

## How to Verify the Bot Has Signed In

### Method 1: Check Login Log File
The bot automatically creates a login log file when it starts.

```bash
# View the login log from a running container
docker exec qgn-container-name cat mt5_login.log

# Or copy it to your host
docker cp qgn-container-name:/app/src/mt5_login.log ./
cat mt5_login.log
```

**Login log contains:**
- Authentication Status (AUTHENTICATED / NOT AUTHENTICATED)
- MT5 Server information
- MT5 Login ID
- Detailed connection log with timestamps
- Trading status (ENABLED / DISABLED)

### Method 2: Run Login Test Script
Test login verification manually without starting the trading loop.

```bash
# Run inside container
docker exec qgn-container-name python test_login.py

# Or from host (after container is running)
docker exec qgn-container-name python -c "from mt5_login_manager import MT5LoginManager; lm = MT5LoginManager(); lm.attempt_login(); lm.print_login_summary()"
```

### Method 3: Check Docker Logs
If startup verification fails, the bot will exit with an error message.

```bash
# View logs
docker logs qgn-container-name

# Watch logs in real-time
docker logs -f qgn-container-name
```

### Method 4: Check Container Status
The bot will only start trading if login is successful.

```bash
# Check if container is still running
docker ps | grep quantumgold-nexus

# If running, login was successful
# If exited, login failed - check mt5_login.log for details
```

## Login Verification Features

### Automatic Login Verification
When the bot starts, it performs these checks:

1. **Authentication Check**
   - Attempts to login to MT5 server
   - Retries up to 3 times with 2-second delays
   - Loads login credentials from config.ini

2. **Account Information Verification**
   - Retrieves account details
   - Verifies account is accessible
   - Confirms account exists on server

3. **Trading Status Verification**
   - Checks if trading is enabled on account
   - Prevents bot from running if trading is disabled
   - Returns specific error if account is restricted

4. **Logging**
   - Creates timestamped connection log
   - Records all login attempts
   - Saves detailed verification report

### What Each Status Means

| Status | Meaning |
|--------|---------|
| **AUTHENTICATED** | Bot successfully logged in to MT5 |
| **NOT AUTHENTICATED** | Login failed - check credentials in config.ini |
| **TRADING ENABLED** | Bot can execute trades |
| **TRADING DISABLED** | Account restricted - check with broker |
| **Account verified** | Account information retrieved successfully |

## Troubleshooting

### Bot exited immediately
**Check:**
1. View login log: `docker exec container-name cat mt5_login.log`
2. Verify credentials: `docker exec container-name cat /app/config.ini | grep -A 3 "\[mt5\]"`
3. Check docker logs: `docker logs container-name`

### "Could not authenticate to MT5"
**Possible causes:**
- Invalid login ID in config.ini
- Invalid password
- Wrong MT5 server name
- Broker server is down

**Fix:**
1. Edit config.ini with correct MT5 credentials
2. Rebuild image: `docker build -t quantumgold-nexus:latest .`
3. Restart container

### "Trading not enabled on this account"
**Possible causes:**
- Account locked by broker
- Demo account with trading disabled
- Account needs verification
- Account suspended

**Fix:**
- Contact your broker to enable trading
- Ensure using live trading account (not demo)

## Example: Full Login Verification Workflow

```bash
# 1. Start bot
docker run -d --name qgn-trade quantumgold-nexus:latest

# 2. Wait for initialization (5-10 seconds)
sleep 5

# 3. Check login status
docker exec qgn-trade cat mt5_login.log

# Expected output:
# ======================================================================
# Authentication Status: AUTHENTICATED
# Server: YOUR_SERVER
# Login: YOUR_LOGIN_ID
# Trading Enabled: YES
# ======================================================================

# 4. If login failed, check logs
docker logs qgn-trade

# 5. If successful, bot is trading
docker ps | grep qgn-trade  # Should show container running
```

## Files Involved

| File | Purpose |
|------|---------|
| `mt5_login_manager.py` | Handles login and verification |
| `test_login.py` | Standalone login test tool |
| `simple_linux.py` | Bot startup with automatic login verification |
| `mt5_login.log` | Login verification log (created at startup) |
| `config.ini` | MT5 credentials and configuration |

## Automation Tips

### Monitor Login Status in CI/CD
```bash
#!/bin/bash
docker run -d --name qgn-health quantumgold-nexus:latest
sleep 5

# Check if authenticated
if grep -q "AUTHENTICATED" mt5_login.log; then
    echo "LOGIN SUCCESS"
    exit 0
else
    echo "LOGIN FAILED"
    docker logs qgn-health
    exit 1
fi
```

### Daily Verification
```bash
# Create cron job to verify bot is still authenticated
0 1 * * * docker exec qgn-trade python test_login.py >> /var/log/qgn-login.log
```

### Email Alert on Login Failure
The bot sends Discord notifications on login success/failure. Configure webhook in config.ini for alerts.
