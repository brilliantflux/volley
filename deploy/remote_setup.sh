#!/usr/bin/env bash
# Установка и обновление volley на VPS. Запускается НА сервере от root,
# идемпотентно: первый прогон разворачивает, следующие обновляют.
set -euo pipefail

NAME=volley
REPO=${VOLLEY_REPO:-git@github.com:brilliantflux/volley.git}
CODE=/opt/$NAME
DATA=/var/$NAME
KEY=/root/.ssh/id_$NAME
GIT_SSH="ssh -i $KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

id -u "$NAME" >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin "$NAME"
mkdir -p "$CODE" "$DATA"

# git отказывается работать в чужом репозитории: код принадлежит volley, git идёт от root
git config --global --get-all safe.directory 2>/dev/null | grep -qx "$CODE" ||
    git config --global --add safe.directory "$CODE"

if [ -d "$CODE/.git" ]; then
    GIT_SSH_COMMAND="$GIT_SSH" git -C "$CODE" pull --ff-only
else
    GIT_SSH_COMMAND="$GIT_SSH" git clone "$REPO" "$CODE"
fi

# .env создаётся один раз пустым: токен вписывает человек, деплой его не трогает
if [ ! -f "$CODE/.env" ]; then
    printf 'VOLLEY_BOT_TOKEN=\nVOLLEY_DB=%s/state.db\n' "$DATA" > "$CODE/.env"
    chmod 600 "$CODE/.env"
fi

if command -v uv >/dev/null 2>&1; then
    [ -d "$CODE/.venv" ] || uv venv "$CODE/.venv" --python 3.12
    uv pip install --python "$CODE/.venv/bin/python" -r "$CODE/requirements.txt"
else
    [ -d "$CODE/.venv" ] || python3 -m venv "$CODE/.venv"
    "$CODE/.venv/bin/pip" install --quiet --upgrade pip
    "$CODE/.venv/bin/pip" install --quiet -r "$CODE/requirements.txt"
fi

chown -R "$NAME:$NAME" "$CODE" "$DATA"
install -m 644 "$CODE/deploy/$NAME.service" "/etc/systemd/system/$NAME.service"
systemctl daemon-reload

if grep -qE '^VOLLEY_BOT_TOKEN=.+' "$CODE/.env"; then
    systemctl enable "$NAME"
    systemctl restart "$NAME"
    sleep 2
    systemctl is-active "$NAME" && echo "✅ $NAME работает"
else
    systemctl enable "$NAME"
    echo "⚠️  токен не вписан. Вставь его в $CODE/.env и запусти: systemctl start $NAME"
fi
