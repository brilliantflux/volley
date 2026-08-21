#!/usr/bin/env bash
# Испытание тестов мутациями: каждый инвариант ломается нарочно, прогон должен
# покраснеть ИМЕННО на своём тесте. Зелёный набор без этого — только имитация.
#
# Запуск: bash scripts/mutations.sh
set -eu

ROOT=$(git rev-parse --show-toplevel)
MUTATE=${MUTATE:-$HOME/git/claude/scripts/mutate_check.sh}
PYTEST=("$ROOT/.venv/bin/python" -m pytest -q)

FAILED=0
run() {
    local title=$1; shift
    echo
    echo "──────── $title"
    if bash "$MUTATE" "$@"; then
        echo "✅ $title"
    else
        echo "❌ $title — испытание провалено"
        FAILED=$((FAILED + 1))
    fi
}

# 1. Главный инвариант: анонимный опрос не отдаёт боту голоса вообще.
run "опрос уходит анонимным" \
    --expect "test_daily_poll_is_non_anonymous_and_pinned" \
    "$ROOT/volley/service.py" "is_anonymous=False" "is_anonymous=True" \
    "$ROOT" "${PYTEST[@]}" tests/test_service.py

# 2. Порог полного состава: 12-й плюс должен закрывать, а не 13-й.
run "закрытие сдвинуто на один голос" \
    --expect "test_full_squad_closes" \
    "$ROOT/volley/domain.py" "count >= full" "count > full" \
    "$ROOT" "${PYTEST[@]}" tests/test_domain.py

# 3. Кворум объявляется один раз за день, а не на каждый голос.
run "кворум объявляется повторно" \
    --expect "test_quorum_not_repeated" \
    "$ROOT/volley/domain.py" "count >= quorum and not poll.quorum_announced" "count >= quorum" \
    "$ROOT" "${PYTEST[@]}" tests/test_domain.py

# 4. Отозванный голос удаляется, а не остаётся висеть плюсом.
run "отзыв голоса ничего не удаляет" \
    --expect "test_retracted_vote_is_deleted_not_kept" \
    "$ROOT/volley/store.py" "DELETE FROM votes WHERE poll_id = ? AND user_id = ?" \
    "SELECT 1 FROM votes WHERE poll_id = ? AND user_id = ?" \
    "$ROOT" "${PYTEST[@]}" tests/test_store.py

# 5. Один опрос в день держится структурой БД, а не аккуратностью кода.
run "UNIQUE(day) снят" \
    --expect "test_one_poll_per_day" \
    "$ROOT/volley/store.py" "day                  TEXT NOT NULL UNIQUE" \
    "day                  TEXT NOT NULL" \
    "$ROOT" "${PYTEST[@]}" tests/test_store.py

# 6. Гейт админа проверяется со ЗАПРЕЩАЮЩЕЙ стороны: пустил ли он рядового.
run "гейт админа пропускает всех" \
    --expect "test_member_cannot_start_poll" \
    "$ROOT/volley/handlers.py" "if message.from_user.id not in {admin.user.id for admin in admins}:" \
    "if False:" \
    "$ROOT" "${PYTEST[@]}" tests/test_handlers.py

# 7. Команды из чужого чата не исполняются.
run "команды принимаются из любого чата" \
    --expect "test_command_from_foreign_chat_is_ignored" \
    "$ROOT/volley/handlers.py" "if chat_id is None or message.chat.id != chat_id:" \
    "if chat_id is None:" \
    "$ROOT" "${PYTEST[@]}" tests/test_handlers.py

# 8. Первая привязка выигрывает: посторонний чат не перетягивает опросы.
run "чужой чат перетягивает привязку" \
    --expect "test_second_group_cannot_hijack_the_bot" \
    "$ROOT/volley/handlers.py" "known = store.chat_id()" "known = None" \
    "$ROOT" "${PYTEST[@]}" tests/test_handlers.py

# 9. Провал закрытия сообщается один раз, а не на каждый голос.
run "ошибка закрытия спамит чат" \
    --expect "test_failed_close_is_reported_once_not_on_every_vote" \
    "$ROOT/volley/service.py" "if not poll.close_error_notified and await self._say(" \
    "if await self._say(" \
    "$ROOT" "${PYTEST[@]}" tests/test_service.py

# 10. Catch-up имеет дедлайн: в 16:00 опрос создавать уже поздно.
run "catch-up без дедлайна" \
    --expect "test_no_catch_up_too_late" \
    "$ROOT/volley/schedule.py" "POLL_TIME <= now.time() < CATCHUP_UNTIL" "POLL_TIME <= now.time()" \
    "$ROOT" "${PYTEST[@]}" tests/test_startup.py

# 11. Замок держит конкурентные апдейты: без него два голоса дают два кворума.
run "замок снят, апдейты идут вперехлёст" \
    --expect "test_concurrent_votes_announce_quorum_once" \
    "$ROOT/volley/service.py" "async with self._lock:" "if True:" \
    "$ROOT" "${PYTEST[@]}" tests/test_service.py

# 12. Провал закрытия не выдаётся за успех.
run "провал закрытия объявляется закрытием" \
    --expect "test_failed_close_never_claims_the_poll_is_closed" \
    "$ROOT/volley/service.py" "if stopped is None:" "if False:" \
    "$ROOT" "${PYTEST[@]}" tests/test_service.py

# 13. Счёт Telegram важнее своего: голоса, потерянные при простое, не теряют игру.
run "счёт Telegram игнорируется" \
    --expect "test_closing_trusts_telegrams_count_over_its_own" \
    "$ROOT/volley/service.py" "plus_count=fresh.telegram_plus_count" "plus_count=None" \
    "$ROOT" "${PYTEST[@]}" tests/test_service.py

# 14. Переезд чужого чата не угоняет привязку.
run "миграция чужого чата угоняет бота" \
    --expect "test_migration_of_a_foreign_chat_does_not_repoint_the_bot" \
    "$ROOT/volley/handlers.py" "if known is not None and known != message.chat.id:" "if False:" \
    "$ROOT" "${PYTEST[@]}" tests/test_handlers.py

# 15. Отказ на команду виден админу, а не только в логе.
run "команда молчит при отказе" \
    --expect "test_admin_gets_an_answer_when_poll_was_not_created" \
    "$ROOT/volley/handlers.py" "await message.reply(texts.poll_not_created_text())" "pass" \
    "$ROOT" "${PYTEST[@]}" tests/test_handlers.py

# 16. Флаг «уже предупредили» ставится только после доставки предупреждения.
run "флаг ошибки ставится до доставки" \
    --expect "test_warning_is_retried_while_it_cannot_be_delivered" \
    "$ROOT/volley/service.py" "if not poll.close_error_notified and await self._say(" \
    "if not poll.close_error_notified or await self._say(" \
    "$ROOT" "${PYTEST[@]}" tests/test_service.py

# 17. «Опрос уже закрыт» — это успех, а не отсутствие прав.
run "уже закрытый опрос считается ошибкой прав" \
    --expect "test_poll_closed_by_hand_is_not_reported_as_missing_rights" \
    "$ROOT/volley/service.py" "if ALREADY_CLOSED_MARKER in str(error):" "if False:" \
    "$ROOT" "${PYTEST[@]}" tests/test_service.py

# 18. Итог считается доведённым только после публикации.
run "закрытие фиксируется без публикации итога" \
    --expect "test_outcome_survives_a_failed_first_announcement" \
    "$ROOT/volley/service.py" "if await self._say(chat_id, texts.closing_text(outcome)):" "if True:" \
    "$ROOT" "${PYTEST[@]}" tests/test_service.py

# 19. То же для состава при полном наборе.
run "состав теряется при сбое отправки" \
    --expect "test_squad_message_failure_keeps_the_poll_open_in_the_ledger" \
    "$ROOT/volley/service.py" "if await self._say(chat_id, texts.squad_full_text(poll.plus)):" "if True:" \
    "$ROOT" "${PYTEST[@]}" tests/test_service.py

# 20. Счёт Telegram сохраняется, иначе повтор публикации «отменит» игру.
run "счёт не сохраняется между попытками" \
    --expect "test_retry_keeps_the_count_telegram_gave_at_first_close" \
    "$ROOT/volley/service.py" "self.store.save_telegram_plus_count(fresh.poll_id, count)" "pass" \
    "$ROOT" "${PYTEST[@]}" tests/test_service.py

# 21. Живая база доращивает схему сама.
run "миграция схемы не выполняется" \
    --expect "test_old_database_gets_the_new_column" \
    "$ROOT/volley/store.py" "        self._migrate()" "        pass" \
    "$ROOT" "${PYTEST[@]}" tests/test_store.py

# 22. Пропущенный джоб наверстывается, а не теряет день.
run "грация планировщика — секунда" \
    --expect "test_scheduler_has_both_daily_jobs_and_forgives_a_late_start" \
    "$ROOT/volley/schedule.py" "misfire_grace_time=MISFIRE_GRACE" "misfire_grace_time=1" \
    "$ROOT" "${PYTEST[@]}" tests/test_tick.py

# 23. Отрицательный вывод из неполных данных запрещён: «игры нет» только по счёту Telegram.
run "неполные данные дают категоричное «игры нет»" \
    --expect "test_no_game_is_hedged_when_the_count_is_only_ours" \
    "$ROOT/volley/texts.py" "if outcome.count is None:" "if False:" \
    "$ROOT" "${PYTEST[@]}" tests/test_texts.py

# 24. Сбой проверки прав не оставляет команду без ответа.
run "сбой проверки прав молчит" \
    --expect "test_command_survives_a_failed_admin_check" \
    "$ROOT/volley/handlers.py" "await message.reply(texts.admin_check_failed_text())" "pass" \
    "$ROOT" "${PYTEST[@]}" tests/test_handlers.py

# 25. Напоминание адресовано только обещавшим ответ и только в открытом опросе.
run "напоминание летит кому попало" \
    --expect "test_no_reminder_in_a_closed_poll" \
    "$ROOT/volley/service.py" "if poll is None or poll.closed or not poll.later:" "if poll is None:" \
    "$ROOT" "${PYTEST[@]}" tests/test_service.py

# 26. Провал создания опроса не выносится в группу.
run "провал создания пишет в группу" \
    --expect "test_failed_poll_creation_stays_out_of_the_group" \
    "$ROOT/volley/service.py" "log.exception(\"не смог создать опрос на %s\", day)" \
    "await self._say(chat_id, texts.error_text(\"создать опрос\", \"x\"))" \
    "$ROOT" "${PYTEST[@]}" tests/test_service.py

echo
if [ "$FAILED" -eq 0 ]; then
    echo "все мутации пойманы ✅"
else
    echo "не поймано мутаций: $FAILED ❌"
fi
exit "$FAILED"
