#!/usr/bin/env bash
set -euo pipefail

APP=/home/bot/football-bot

apt-get update -q
apt-get install -y -q python3 python3-venv

id -u bot >/dev/null 2>&1 || useradd -m -s /bin/bash bot
chown -R bot:bot "$APP"

sudo -u bot python3 -m venv "$APP/.venv"
sudo -u bot "$APP/.venv/bin/pip" install -q --upgrade pip
sudo -u bot "$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"

cp "$APP/deploy/football-bot.service" /etc/systemd/system/football-bot.service
systemctl daemon-reload
systemctl enable --now football-bot

echo
echo "Готово. Бот запущен как служба football-bot."
echo "  статус:      systemctl status football-bot"
echo "  лог:         tail -f $APP/logs/bot.log"
echo "  перезапуск:  systemctl restart football-bot"
