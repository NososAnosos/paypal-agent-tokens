#!/bin/bash
# Spike 4 listener loop for the 2026-11-05 sitting: 04_webhook.py runs in 20-min
# windows; relaunch it with the same tunnel URL so the listener stays warm all day.
# Stop with: pkill -f run_spike4_loop.sh ; pkill -f 04_webhook.py
cd ~/Projects/paypal-agent-tokens || exit 1
URL="https://honolulu-allow-gather-gst.trycloudflare.com/webhooks/paypal"
while true; do
  echo "=== spike4 cycle start $(date -Is) ===" >> sitting-spike4.log
  python3 spikes/04_webhook.py "$URL" 8804 >> sitting-spike4.log 2>&1
  echo "=== spike4 cycle ended $(date -Is) — restarting in 3s ===" >> sitting-spike4.log
  sleep 3
done
