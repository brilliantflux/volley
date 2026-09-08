"""FR-5, FR-6: привязка к группе, миграция, гейт по админам."""

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace

from volley import handlers, settings
from volley.domain import PLUS
from volley.store import Store

CHAT_ID = -1001234
OTHER_CHAT = -1009999
ADMIN_ID = 482130268
MEMBER_ID = 777


@dataclass
class FakeBot:
    admins: tuple[int, ...] = (ADMIN_ID,)
    calls: list[tuple] = field(default_factory=list)
    fail_admins: bool = False

    async def get_chat_administrators(self, chat_id):
        self.calls.append(("get_chat_administrators", chat_id))
        if self.fail_admins:
            raise RuntimeError("Telegram server says - Bad Gateway")
        return [SimpleNamespace(user=SimpleNamespace(id=uid)) for uid in self.admins]

    async def send_message(self, chat_id, text, **kw):
        self.calls.append(("send_message", chat_id, text))

    def named(self, name):
        return [c for c in self.calls if c[0] == name]


@dataclass
class FakeService:
    calls: list[tuple] = field(default_factory=list)
    status: str = "статус"
    open_result: bool = True

    async def handle_vote(self, poll_id, voter, option_ids):
        self.calls.append(("handle_vote", poll_id, voter, tuple(option_ids)))

    async def open_poll(self, day):
        self.calls.append(("open_poll", day))
        return self.open_result

    async def close_poll(self, poll):
        self.calls.append(("close_poll", poll.poll_id if poll else None))

    async def status_text(self):
        return self.status


@dataclass
class FakeMessage:
    chat_id: int = CHAT_ID
    user_id: int = ADMIN_ID
    migrate_to_chat_id: int | None = None
    chat_type: str = "supergroup"
    replies: list[str] = field(default_factory=list)

    @property
    def chat(self):
        return SimpleNamespace(id=self.chat_id, type=self.chat_type)

    @property
    def from_user(self):
        return SimpleNamespace(id=self.user_id)

    async def reply(self, text, **kw):
        self.replies.append(text)


def member_update(chat_id=CHAT_ID, status="administrator", chat_type="supergroup"):
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id, type=chat_type),
        new_chat_member=SimpleNamespace(status=status),
    )


def run(coro):
    return asyncio.run(coro)


def store_with_chat(tmp_path, chat_id=CHAT_ID):
    store = Store(tmp_path / "state.db")
    store.set_chat_id(chat_id)
    return store


# --- FR-6: привязка к группе ------------------------------------------------


def test_bot_added_to_group_remembers_chat_and_greets(tmp_path):
    store = Store(tmp_path / "state.db")
    bot = FakeBot()
    run(handlers.on_my_chat_member(member_update(), store=store, bot=bot))

    assert store.chat_id() == CHAT_ID
    assert bot.named("send_message")


def test_second_group_cannot_hijack_the_bot(tmp_path):
    """Юзернейм бота публичный: кто угодно может добавить его в свой чат."""
    store = store_with_chat(tmp_path)
    bot = FakeBot()
    run(handlers.on_my_chat_member(member_update(chat_id=OTHER_CHAT), store=store, bot=bot))

    assert store.chat_id() == CHAT_ID
    assert bot.named("send_message") == []


def test_bot_kicked_does_not_change_binding(tmp_path):
    store = store_with_chat(tmp_path)
    run(handlers.on_my_chat_member(member_update(status="left"), store=store, bot=FakeBot()))
    assert store.chat_id() == CHAT_ID


def test_private_chat_never_becomes_the_group(tmp_path):
    store = Store(tmp_path / "state.db")
    run(
        handlers.on_my_chat_member(
            member_update(chat_id=555, chat_type="private", status="member"),
            store=store,
            bot=FakeBot(),
        )
    )
    assert store.chat_id() is None


def test_migration_to_supergroup_updates_chat_id(tmp_path):
    """При апгрейде обычной группы chat_id меняется — иначе бот замолчит навсегда."""
    store = store_with_chat(tmp_path)
    message = FakeMessage(chat_id=CHAT_ID, migrate_to_chat_id=-1002222)
    run(handlers.on_migrate(message, store=store))
    assert store.chat_id() == -1002222


# --- голоса -----------------------------------------------------------------


def test_poll_answer_passes_voter_to_service(tmp_path):
    service = FakeService()
    answer = SimpleNamespace(
        poll_id="pid1",
        option_ids=[PLUS],
        user=SimpleNamespace(id=42, first_name="Первый", username="player1"),
    )
    run(handlers.on_poll_answer(answer, service=service))

    (call,) = service.calls
    assert call[0] == "handle_vote" and call[1] == "pid1" and call[3] == (PLUS,)
    assert call[2].user_id == 42 and call[2].username == "player1"


def test_anonymous_channel_vote_is_ignored():
    service = FakeService()
    answer = SimpleNamespace(poll_id="pid1", option_ids=[PLUS], user=None)
    run(handlers.on_poll_answer(answer, service=service))
    assert service.calls == []


# --- FR-5: команды только админам -------------------------------------------


def test_admin_can_start_poll(tmp_path):
    store, service, bot = store_with_chat(tmp_path), FakeService(), FakeBot()
    message = FakeMessage(user_id=ADMIN_ID)
    run(handlers.cmd_poll(message, service=service, store=store, bot=bot))
    assert [c[0] for c in service.calls] == ["open_poll"]


def test_member_cannot_start_poll(tmp_path):
    store, service, bot = store_with_chat(tmp_path), FakeService(), FakeBot()
    message = FakeMessage(user_id=MEMBER_ID)
    run(handlers.cmd_poll(message, service=service, store=store, bot=bot))
    assert service.calls == []
    assert message.replies, "отказ должен быть виден тому, кто позвал"


def test_member_cannot_close_poll(tmp_path):
    store, service, bot = store_with_chat(tmp_path), FakeService(), FakeBot()
    message = FakeMessage(user_id=MEMBER_ID)
    run(handlers.cmd_close(message, service=service, store=store, bot=bot))
    assert service.calls == []


def test_member_cannot_read_status(tmp_path):
    store, service, bot = store_with_chat(tmp_path), FakeService(), FakeBot()
    message = FakeMessage(user_id=MEMBER_ID)
    run(handlers.cmd_status(message, service=service, store=store, bot=bot))
    assert message.replies and "админ" in message.replies[0].lower()


def test_command_from_foreign_chat_is_ignored(tmp_path):
    store, service, bot = store_with_chat(tmp_path), FakeService(), FakeBot()
    message = FakeMessage(chat_id=OTHER_CHAT, user_id=ADMIN_ID)
    run(handlers.cmd_poll(message, service=service, store=store, bot=bot))

    assert service.calls == []
    assert bot.named("get_chat_administrators") == [], "в чужом чате даже права не спрашиваем"


def test_close_without_open_poll_answers_politely(tmp_path):
    store, service, bot = store_with_chat(tmp_path), FakeService(), FakeBot()
    message = FakeMessage(user_id=ADMIN_ID)
    run(handlers.cmd_close(message, service=service, store=store, bot=bot))

    assert service.calls == []
    assert message.replies


def test_close_closes_the_open_poll(tmp_path):
    store, service, bot = store_with_chat(tmp_path), FakeService(), FakeBot()
    store.add_poll(day="2026-08-21", poll_id="pid1", message_id=5)
    message = FakeMessage(user_id=ADMIN_ID)
    run(handlers.cmd_close(message, service=service, store=store, bot=bot))

    assert service.calls == [("close_poll", "pid1")]


def test_status_reaches_admin(tmp_path):
    store, service, bot = store_with_chat(tmp_path), FakeService(), FakeBot()
    message = FakeMessage(user_id=ADMIN_ID)
    run(handlers.cmd_status(message, service=service, store=store, bot=bot))
    assert message.replies == ["статус"]


def test_migration_of_a_foreign_chat_does_not_repoint_the_bot(tmp_path):
    """Бота могли добавить и в другой чат: его апгрейд не должен угонять привязку."""
    store = store_with_chat(tmp_path)
    message = FakeMessage(chat_id=OTHER_CHAT, migrate_to_chat_id=-1003333)
    run(handlers.on_migrate(message, store=store))
    assert store.chat_id() == CHAT_ID


def test_admin_gets_an_answer_when_poll_was_not_created(tmp_path):
    """Молчание в ответ на команду читается как «бот сломался»."""
    store, bot = store_with_chat(tmp_path), FakeBot()
    service = FakeService(open_result=False)
    message = FakeMessage(user_id=ADMIN_ID)
    run(handlers.cmd_poll(message, service=service, store=store, bot=bot))
    assert message.replies


def test_admin_gets_no_noise_when_poll_was_created(tmp_path):
    store, service, bot = store_with_chat(tmp_path), FakeService(), FakeBot()
    message = FakeMessage(user_id=ADMIN_ID)
    run(handlers.cmd_poll(message, service=service, store=store, bot=bot))
    assert message.replies == [], "опрос виден сам, лишнее сообщение не нужно"


def test_command_survives_a_failed_admin_check(tmp_path):
    """Сеть подвела на проверке прав — админ должен увидеть отказ, а не тишину."""
    store, service = store_with_chat(tmp_path), FakeService()
    bot = FakeBot(fail_admins=True)
    message = FakeMessage(user_id=ADMIN_ID)
    run(handlers.cmd_poll(message, service=service, store=store, bot=bot))

    assert service.calls == []
    assert message.replies


# --- настройки: команды админа в группе и в личке ---------------------------


def private(user_id=ADMIN_ID):
    """В личке chat.id совпадает с id пользователя — привязка группы тут ни при чём."""
    return FakeMessage(chat_id=user_id, user_id=user_id, chat_type="private")


def cmd(args: str | None):
    return SimpleNamespace(args=args)


def test_admin_changes_a_setting_from_a_private_chat(tmp_path):
    store, bot = store_with_chat(tmp_path), FakeBot()
    run(handlers.cmd_set(private(), command=cmd("close_time 18-00"), store=store, bot=bot))

    assert settings.value(store, "close_time") == "18:00"
    assert bot.named("get_chat_administrators") == [("get_chat_administrators", CHAT_ID)], (
        "права в личке проверяются по списку админов ПРИВЯЗАННОЙ группы"
    )


def test_stranger_cannot_change_settings_in_private(tmp_path):
    store, bot = store_with_chat(tmp_path), FakeBot()
    message = private(MEMBER_ID)
    run(handlers.cmd_set(message, command=cmd("close_time 18-00"), store=store, bot=bot))

    assert settings.value(store, "close_time") == "16:30"
    assert message.replies and "админ" in message.replies[0].lower()


def test_member_in_the_group_cannot_change_settings(tmp_path):
    store, bot = store_with_chat(tmp_path), FakeBot()
    message = FakeMessage(user_id=MEMBER_ID)
    run(handlers.cmd_set(message, command=cmd("close_time 18-00"), store=store, bot=bot))
    assert settings.value(store, "close_time") == "16:30"


def test_private_command_before_the_bot_knows_the_group(tmp_path):
    """Бота ещё не добавили в группу: спрашивать админов не у кого, но и падать нельзя."""
    store, bot = Store(tmp_path / "state.db"), FakeBot()
    message = private()
    run(handlers.cmd_set(message, command=cmd("close_time 18-00"), store=store, bot=bot))

    assert settings.value(store, "close_time") == "16:30"
    assert message.replies


def test_admin_sees_the_new_value_in_the_answer(tmp_path):
    store, bot = store_with_chat(tmp_path), FakeBot()
    message = private()
    run(handlers.cmd_set(message, command=cmd("game_time 19-00"), store=store, bot=bot))
    assert message.replies and "19" in message.replies[0]


def test_bad_value_is_explained_and_not_saved(tmp_path):
    store, bot = store_with_chat(tmp_path), FakeBot()
    message = private()
    run(handlers.cmd_set(message, command=cmd("close_time вечером"), store=store, bot=bot))

    assert settings.value(store, "close_time") == "16:30"
    assert message.replies, "молчание в ответ на команду читается как поломка"


def test_unknown_setting_is_explained(tmp_path):
    store, bot = store_with_chat(tmp_path), FakeBot()
    message = private()
    run(handlers.cmd_set(message, command=cmd("кворум 5"), store=store, bot=bot))
    assert message.replies


def test_set_without_arguments_shows_what_it_expects(tmp_path):
    store, bot = store_with_chat(tmp_path), FakeBot()
    message = private()
    run(handlers.cmd_set(message, command=cmd(None), store=store, bot=bot))
    assert message.replies and "close_time" in message.replies[0]


def test_one_setting_at_a_time_the_rest_are_untouched(tmp_path):
    store, bot = store_with_chat(tmp_path), FakeBot()
    run(handlers.cmd_set(private(), command=cmd("poll_time 08:00"), store=store, bot=bot))

    assert settings.value(store, "poll_time") == "08:00"
    assert settings.value(store, "close_time") == "16:30"
    assert settings.value(store, "option_plus") == "Плюс"


def test_option_text_with_spaces_survives_intact(tmp_path):
    store, bot = store_with_chat(tmp_path), FakeBot()
    run(
        handlers.cmd_set(
            private(), command=cmd("option_later Отвечу до обеда"), store=store, bot=bot
        )
    )
    assert settings.value(store, "option_later") == "Отвечу до обеда"


def test_settings_command_shows_every_current_value(tmp_path):
    store, bot = store_with_chat(tmp_path), FakeBot()
    settings.set_value(store, "close_time", "18:00")
    message = private()
    run(handlers.cmd_settings(message, store=store, bot=bot))

    (answer,) = message.replies
    assert "18:00" in answer
    for key in ("game_time", "poll_time", "reminder_time", "close_time", "option_plus"):
        assert key in answer, f"{key} не видно в /settings"


def test_settings_is_not_for_members(tmp_path):
    store, bot = store_with_chat(tmp_path), FakeBot()
    message = FakeMessage(user_id=MEMBER_ID)
    run(handlers.cmd_settings(message, store=store, bot=bot))
    assert message.replies and "админ" in message.replies[0].lower()
