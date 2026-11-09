#!/bin/bash
# PayPal sitting prep 2026-11-05: demo server (sandbox) on 8801/8802/8803
cd ~/Projects/paypal-agent-tokens/server || exit 1
if [ ! -f ~/.config/paypal-sitting/keys.env ]; then
  mkdir -p ~/.config/paypal-sitting
  python3 -c "import secrets; print(\"AGENT_API_KEY=\"+secrets.token_hex(16)); print(\"HUMAN_API_KEY=\"+secrets.token_hex(16))" > ~/.config/paypal-sitting/keys.env
  chmod 600 ~/.config/paypal-sitting/keys.env
fi
set -a; . ~/.config/paypal-sitting/keys.env; set +a
export LEDGER_DB=$HOME/Projects/paypal-agent-tokens/server/tokens-sitting-20261105.db
exec python3 -m tokenservice --sandbox
