#!/bin/sh
# Sobe o librespot (Spotify Connect "Cassandra"). Chamado pelo cassandra-spotify.service.
# Sem credencial guardada ainda, entra na conta com o token que a Cassandra deixa em $CACHE/access_token
# depois do login do Spotify na UI (escopo "streaming"); o librespot então guarda a própria credencial no
# cache e, dali em diante, entra sozinho. O token vai por variável de ambiente (não aparece no ps) e o
# arquivo é apagado assim que lido.
CACHE="$HOME/.cache/cassandra-spotify"
STATE="$HOME/.local/state/cassandra-spotify"
mkdir -p "$CACHE" "$STATE"
if [ -s "$CACHE/access_token" ]; then
    LIBRESPOT_ACCESS_TOKEN="$(cat "$CACHE/access_token")"
    export LIBRESPOT_ACCESS_TOKEN
    rm -f "$CACHE/access_token"
fi
exec "$HOME/.local/bin/librespot" --name Cassandra --device-type speaker --backend pulseaudio \
    --bitrate 320 --initial-volume 70 --enable-volume-normalisation \
    --cache "$CACHE" --system-cache "$STATE" --cache-size-limit 500M
