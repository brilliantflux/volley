#!/usr/bin/env bash
# Деплой volley на сервер. Локальный запуск: bash deploy/deploy.sh
#
# Адрес сервера в git не хранится: положи его в deploy/target.env (gitignored)
# по образцу deploy/target.env.example либо задай VOLLEY_SSH_HOST в окружении.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
[ -f "$HERE/target.env" ] && . "$HERE/target.env"
HOST=${VOLLEY_SSH_HOST:?не задан VOLLEY_SSH_HOST — см. deploy/target.env.example}

scp -q "$HERE/remote_setup.sh" "$HOST:/tmp/volley_setup.sh"
ssh "$HOST" "bash /tmp/volley_setup.sh"
