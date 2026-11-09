#!/bin/bash
# Runner: PayPal wiring pass via cursor-agent (print mode).
cd /home/nosos/Projects/paypal-agent-tokens || exit 1
set -a
. /home/nosos/.config/fleet/cursor.env
set +a
exec timeout 5400 /home/nosos/.local/bin/cursor-agent -p "$(cat .cursor-prompt-wiring.txt)" --trust
