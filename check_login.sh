#!/bin/bash
# Quick Reference: Login Verification Commands

echo "=========================================="
echo "QuantumGold-Nexus Login Verification"
echo "=========================================="

# Replace 'qgn-trade' with your container name

CONTAINER_NAME="${1:-qgn-trade}"

echo ""
echo "[1] Check if container is running:"
docker ps | grep "$CONTAINER_NAME" && echo "RUNNING" || echo "NOT RUNNING"

echo ""
echo "[2] View login verification log:"
docker exec "$CONTAINER_NAME" cat mt5_login.log 2>/dev/null || echo "Log not available yet"

echo ""
echo "[3] Check bot process:"
docker top "$CONTAINER_NAME" 2>/dev/null | grep -i python && echo "Bot process ACTIVE" || echo "Bot process NOT FOUND"

echo ""
echo "[4] Run login test:"
docker exec "$CONTAINER_NAME" python test_login.py 2>/dev/null | tail -10

echo ""
echo "[5] Check MT5 credentials in config:"
docker exec "$CONTAINER_NAME" grep -A 3 "\[mt5\]" /app/config.ini

echo ""
echo "[6] View full container logs (last 20 lines):"
docker logs "$CONTAINER_NAME" 2>&1 | tail -20

echo ""
echo "=========================================="
