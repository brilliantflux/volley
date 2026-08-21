#!/usr/bin/env bash
# Проверка развёрнутого сервиса НА СЕРВЕРЕ: юнит стартует, база пишется под
# песочницей systemd, до api.telegram.org есть связь.
#
# Если токен уже вписан — только показывает состояние и ничего не трогает.
# Если токена нет — временно ставит заведомо неверный (ожидаемый ответ 401),
# после проверки возвращает .env как было.
set -euo pipefail

NAME=volley
CODE=/opt/$NAME
DATA=/var/$NAME
ENV_FILE=$CODE/.env

if grep -qE '^VOLLEY_BOT_TOKEN=.+' "$ENV_FILE"; then
    echo "== токен вписан, .env не трогаю"
    systemctl is-active "$NAME" || true
    journalctl -u "$NAME" -n 15 --no-pager
    exit 0
fi

echo "== токена нет: проверяю юнит фиктивным токеном (ждём 401 от Telegram)"
BACKUP=$(mktemp)
cp "$ENV_FILE" "$BACKUP"
restore() {
    cp "$BACKUP" "$ENV_FILE"
    rm -f "$BACKUP"
    chown "$NAME:$NAME" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    systemctl stop "$NAME" 2>/dev/null || true
    echo "== .env возвращён, сервис остановлен"
}
trap restore EXIT

sed -i 's|^VOLLEY_BOT_TOKEN=.*|VOLLEY_BOT_TOKEN=123456:FAKE-TOKEN-FOR-SELFTEST|' "$ENV_FILE"
systemctl start "$NAME" || true
sleep 20  # импорт aiogram на этом VPS занимает ~12 секунд, раньше проверять нечего

echo "== журнал"
journalctl -u "$NAME" -n 25 --no-pager

echo "== база"
ls -la "$DATA" || echo "‼ база не создана — песочница юнита не пускает запись"
