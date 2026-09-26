#!/bin/sh
# Reinicia a Cassandra (serviço systemd do usuário, que já sobe sozinho no boot). Log: /tmp/personal-assistant.log
systemctl --user restart cassandra-assistant
sleep 8
if systemctl --user is-active --quiet cassandra-assistant && pgrep -f 'personal-assistant/[.]venv/bin/python main[.]py' > /dev/null; then
  echo "Cassandra rodando"; tail -n 4 /tmp/personal-assistant.log
else
  echo "Cassandra NAO subiu:"; systemctl --user status cassandra-assistant --no-pager | tail -5; tail -n 20 /tmp/personal-assistant.log; exit 1
fi
