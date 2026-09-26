# Cassandra no Raspberry Pi (sobe sozinha no boot)

Arquivos que rodam hoje no Pi, fora do código da Cassandra: serviços **systemd do usuário** (sem `sudo`)
e scripts de apoio.

| Arquivo | Vai para | O que faz |
|---|---|---|
| `cassandra-assistant.service` | `~/.config/systemd/user/` | A Cassandra. Sobe no boot, reinicia sozinha se cair. Log: `/tmp/personal-assistant.log` |
| `cassandra-tunnel.service` | `~/.config/systemd/user/` | Túnel público da Cloudflare (quick tunnel → `localhost:8080`), usado pelo site. URL em `/tmp/cloudflared.log` |
| `cassandra-netlify-sync.service` | `~/.config/systemd/user/` | Republica o site no Netlify quando a URL do túnel (ou a página) muda — ex.: depois de um reboot |
| `cassandra-netlify-sync.py` | `~/.local/bin/` | O sincronizador (só biblioteca padrão do Python) |
| `cassandra-spotify.service` | `~/.config/systemd/user/` | Spotify Connect: o Pi vira o dispositivo "Cassandra" no Spotify (librespot → PipeWire). Log: `/tmp/cassandra-spotify.log` |
| `cassandra-start.sh` | `~/.local/bin/` | Reinicia a Cassandra e mostra o fim do log |
| `cassandra-tunnel.sh` | `~/.local/bin/` | Reinicia o túnel e imprime a URL nova |

## Instalação

```bash
cd ~/Desktop/personal-assistant/scripts/raspberry-pi
mkdir -p ~/.local/bin ~/.config/systemd/user ~/.config/cassandra
cp cassandra-*.service ~/.config/systemd/user/
cp cassandra-netlify-sync.py cassandra-start.sh cassandra-tunnel.sh ~/.local/bin/
chmod +x ~/.local/bin/cassandra-*

# cloudflared (binário avulso, sem sudo)
curl -fsSL -o ~/.local/bin/cloudflared \
  https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64
chmod +x ~/.local/bin/cloudflared

# token do Netlify (Netlify > User settings > Applications > Personal access tokens) + id do site
read -s -p "Token: " T && printf 'NETLIFY_AUTH_TOKEN=%s\nNETLIFY_SITE_ID=<id-do-site>\n' "$T" \
  > ~/.config/cassandra/netlify.env && chmod 600 ~/.config/cassandra/netlify.env

# serviços do usuário sobem no boot mesmo sem login
loginctl enable-linger
systemctl --user daemon-reload
systemctl --user enable --now cassandra-assistant cassandra-tunnel cassandra-netlify-sync
```

Sem o `netlify.env` o serviço de sincronização simplesmente não inicia (a Cassandra e o túnel funcionam).

## Cuidados

- **Não coloque `After=default.target`** no serviço da Cassandra: junto com o `After=` do túnel isso forma um
  ciclo e, no boot, o systemd descarta o túnel para quebrá-lo (só aparece num reboot de verdade).
- Os logs do túnel usam `truncate:` (e não `file:`): o arquivo é zerado a cada início, senão a URL antiga
  continua no começo dele.
- Áudio: os players usam `pw-play` (PipeWire). Para o microfone plugado depois ser adotado sozinho, instale
  `sudo apt install pipewire-alsa`.

## Spotify (librespot, sem sudo)

```bash
# o binário do librespot vem do pacote do raspotify (só extrai, não instala nada no sistema)
cd /tmp && curl -sSL -o raspotify.deb \
  https://github.com/dtcooper/raspotify/releases/download/0.48.3/raspotify_0.48.3.librespot.v0.8.0-939dc5e_arm64.deb
dpkg-deb -x raspotify.deb rsp && cp rsp/usr/bin/librespot ~/.local/bin/
cp ~/Desktop/personal-assistant/scripts/raspberry-pi/cassandra-spotify.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now cassandra-spotify
```

Na primeira vez, abra o app do Spotify no celular (mesmo Wi-Fi) e escolha **Cassandra** na lista de
dispositivos: a credencial fica no cache e ele entra sozinho depois de reboots. Depois conecte a conta na UI
(Configurações > Spotify) para a Cassandra poder mandar tocar.
