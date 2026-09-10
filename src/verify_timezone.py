#!/usr/bin/env python3
"""Verify container timezone is set correctly"""

from datetime import datetime
import os
import subprocess

print("=" * 70)
print("Container Timezone Verification")
print("=" * 70)

# Check system timezone
print("\n[System Information]")
print(f"Python timezone offset: {datetime.now().strftime('%z')}")
print(f"Python time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}")

# Check environment variable
tz_env = os.environ.get('TZ', 'Not set')
print(f"TZ environment variable: {tz_env}")

# Check /etc/timezone
try:
    result = subprocess.run(['cat', '/etc/timezone'], capture_output=True, text=True)
    print(f"/etc/timezone: {result.stdout.strip()}")
except:
    print("/etc/timezone: Not accessible")

# Check date command
try:
    result = subprocess.run(['date'], capture_output=True, text=True)
    print(f"System date: {result.stdout.strip()}")
except:
    print("System date: Not accessible")

# Verify HKT
print("\n[Timezone Verification]")
hkt_offset = datetime.now().strftime('%z')
if hkt_offset == '+0800':
    print("✓ Container timezone is correctly set to HKT (UTC+8)")
else:
    print(f"✗ Container timezone is {hkt_offset} (expected +0800 for HKT)")

# Show trading hours in HKT
print("\n[Trading Scheduled Times (HKT)]")
print("Current time: " + datetime.now().strftime('%Y-%m-%d %H:%M:%S (HKT)'))
print("\nBot scheduling:")
print("  - 20:00 (8:00 PM) HKT: Trigger trades")
print("  - 04:45 (4:45 AM) HKT: Close all positions")
print("  - 06:00 (6:00 AM) HKT: Reset trade count")

print("\n" + "=" * 70)
