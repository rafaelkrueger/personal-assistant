#!/bin/sh
# Reinicia o túnel público (serviço systemd do usuário) e imprime a URL nova.
# O site no Netlify se atualiza sozinho em até ~30 s (serviço cassandra-netlify-sync).
RE='https://[a-z0-9-]+\.trycloudflare\.com'
old=$(grep -oE "$RE" /tmp/cloudflared.log 2>/dev/null | head -1)
systemctl --user restart cassandra-tunnel
for i in $(seq 1 40); do
  url=$(grep -oE "$RE" /tmp/cloudflared.log 2>/dev/null | head -1)
  if [ -n "$url" ] && [ "$url" != "$old" ]; then echo "$url"; exit 0; fi
  sleep 1
done
echo "tunel nao subiu:" >&2; tail -5 /tmp/cloudflared.log >&2; exit 1
