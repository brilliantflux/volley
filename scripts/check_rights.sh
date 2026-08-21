#!/usr/bin/env bash
# Что бот реально может в своей группе: статус, права, ограничения участников.
# Запускается НА сервере от root: bash /tmp/volley_rights.sh
set -euo pipefail

set -a
. /opt/volley/.env
set +a

CHAT=$(python3 -c "import sqlite3;print(sqlite3.connect('/var/volley/state.db').execute(\"select value from settings where key='chat_id'\").fetchone()[0])")
ME=$(curl -s "https://api.telegram.org/bot$VOLLEY_BOT_TOKEN/getMe" | python3 -c "import json,sys;print(json.load(sys.stdin)['result']['id'])")

echo "== статус бота в чате $CHAT"
curl -s "https://api.telegram.org/bot$VOLLEY_BOT_TOKEN/getChatMember?chat_id=$CHAT&user_id=$ME" |
    python3 -m json.tool

echo "== что разрешено участникам группы"
curl -s "https://api.telegram.org/bot$VOLLEY_BOT_TOKEN/getChat?chat_id=$CHAT" |
    python3 -c "import json,sys;d=json.load(sys.stdin)['result'];print('title:',d.get('title'));print('type:',d.get('type'));print('permissions:',json.dumps(d.get('permissions',{}),ensure_ascii=False,indent=1))"
