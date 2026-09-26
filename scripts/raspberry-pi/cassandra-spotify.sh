#!/bin/sh
# Sobe o librespot (Spotify Connect "Cassandra"). Chamado pelo cassandra-spotify.service.
# Sem credencial guardada ainda, sobe em modo de pareamento: escreve no log (/tmp/cassandra-spotify.log) um
# link spotify.com/pair?code=XXXXXX — a Cassandra mostra o código na aba Música e, depois que ele é digitado
# no site do Spotify, o librespot guarda a credencial no cache e passa a entrar sozinho (inclusive após reboot).
# (Um token do app da Cassandra não serve: o Spotify só aceita o Connect com o login do próprio librespot.)
CACHE="$HOME/.cache/cassandra-spotify"
STATE="$HOME/.local/state/cassandra-spotify"
mkdir -p "$CACHE" "$STATE"
PAIR=""
[ -s "$STATE/credentials.json" ] || PAIR="--enable-device-auth"
exec "$HOME/.local/bin/librespot" --name Cassandra --device-type speaker --backend pulseaudio \
    --bitrate 320 --initial-volume 70 --enable-volume-normalisation \
    --cache "$CACHE" --system-cache "$STATE" --cache-size-limit 500M $PAIR
