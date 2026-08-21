"""FR-1..FR-4 и SC-4: поведение бота целиком, на фейковом Telegram."""

import asyncio
from dataclasses import dataclass, field
from datetime import date

from volley.domain import LATER, MINUS, PLUS, Voter
from volley.service import VolleyService
from volley.store import Store


@dataclass
class FakePoll:
    id: str


@dataclass
class FakeMessage:
    message_id: int
    poll: FakePoll


@dataclass
class FakePollOption:
    voter_count: int


@dataclass
class FakeStoppedPoll:
    """Что stopPoll возвращает в реальности: опрос с настоящими счётчиками."""

    options: list[FakePollOption]


@dataclass
class FakeBot:
    """Фейковый Telegram: пишет вызовы, умеет падать и отвечать не мгновенно.

    delay больше нуля открывает окно между проверкой состояния и записью —
    без него гонки конкурентных апдейтов в тестах не воспроизводятся.
    """

    fail_on: tuple[str, ...] = ()
    calls: list[tuple] = field(default_factory=list)
    delay: float = 0.0
    plus_voter_count: int | None = None
    stop_poll_error: str = "Forbidden: not enough rights"
    _next_id: int = 100

    async def send_poll(self, chat_id, question, options, is_anonymous, **kw):
        self._fail_maybe("send_poll")
        await self._wait()
        self._next_id += 1
        self.calls.append(("send_poll", chat_id, question, tuple(options), is_anonymous))
        return FakeMessage(message_id=self._next_id, poll=FakePoll(id=f"pid{self._next_id}"))

    async def stop_poll(self, chat_id, message_id, **kw):
        if "stop_poll" in self.fail_on:
            raise RuntimeError(self.stop_poll_error)
        await self._wait()
        self.calls.append(("stop_poll", chat_id, message_id))
        plus = self.plus_voter_count
        # None — Telegram счётчика не дал, сервис обязан обойтись своими данными
        return FakeStoppedPoll(options=[FakePollOption(plus)] if plus is not None else [])

    async def send_message(self, chat_id, text, **kw):
        self._fail_maybe("send_message")
        await self._wait()
        self.calls.append(("send_message", chat_id, text))
        self._next_id += 1
        return FakeMessage(message_id=self._next_id, poll=None)

    async def pin_chat_message(self, chat_id, message_id, **kw):
        self._fail_maybe("pin_chat_message")
        self.calls.append(("pin_chat_message", chat_id, message_id))

    async def unpin_chat_message(self, chat_id, message_id, **kw):
        self._fail_maybe("unpin_chat_message")
        self.calls.append(("unpin_chat_message", chat_id, message_id))

    async def _wait(self):
        if self.delay:
            await asyncio.sleep(self.delay)

    def _fail_maybe(self, name):
        if name in self.fail_on:
            raise RuntimeError(f"Forbidden: {name} not allowed")

    def named(self, name):
        return [c for c in self.calls if c[0] == name]

    def texts(self):
        return [c[2] for c in self.calls if c[0] == "send_message"]


CHAT_ID = -1001234


def build(tmp_path, fail_on=(), with_chat=True):
    store = Store(tmp_path / "state.db")
    if with_chat:
        store.set_chat_id(CHAT_ID)
    bot = FakeBot(fail_on=fail_on)
    return bot, store, VolleyService(bot=bot, store=store)


def voter(n: int) -> Voter:
    return Voter(user_id=n, first_name=f"Игрок{n}", username=f"user{n}")


def run(coro):
    return asyncio.run(coro)


async def open_and_vote(service, store, plus_count, option=PLUS, day=date(2026, 8, 21)):
    await service.open_poll(day)
    poll = store.poll_for_day(day.isoformat())
    for n in range(1, plus_count + 1):
        await service.handle_vote(poll.poll_id, voter(n), [option])
    return poll


# --- FR-1 -------------------------------------------------------------------


def test_daily_poll_is_non_anonymous_and_pinned(tmp_path):
    bot, store, service = build(tmp_path)
    run(service.open_poll(date(2026, 8, 21)))

    (call,) = bot.named("send_poll")
    assert call[1] == CHAT_ID
    assert call[2] == "21.08 (пт) Игра 18-00"
    assert call[3] == ("Плюс", "Минус", "Ответ до 16-00")
    assert call[4] is False, "анонимный опрос не даёт боту голоса — бот бесполезен"
    assert bot.named("pin_chat_message")


def test_poll_is_stored_for_the_day(tmp_path):
    bot, store, service = build(tmp_path)
    run(service.open_poll(date(2026, 8, 21)))
    assert store.poll_for_day("2026-08-21") is not None


def test_second_poll_same_day_is_not_created(tmp_path):
    bot, store, service = build(tmp_path)
    run(service.open_poll(date(2026, 8, 21)))
    run(service.open_poll(date(2026, 8, 21)))
    assert len(bot.named("send_poll")) == 1


def test_previous_pin_is_removed_before_new_one(tmp_path):
    bot, store, service = build(tmp_path)
    run(service.open_poll(date(2026, 8, 20)))
    run(service.open_poll(date(2026, 8, 21)))
    assert bot.named("unpin_chat_message")


def test_without_known_chat_nothing_is_sent(tmp_path):
    bot, store, service = build(tmp_path, with_chat=False)
    run(service.open_poll(date(2026, 8, 21)))
    assert bot.calls == []


def test_pin_failure_does_not_break_the_poll(tmp_path):
    bot, store, service = build(tmp_path, fail_on=("pin_chat_message",))
    run(service.open_poll(date(2026, 8, 21)))
    assert store.poll_for_day("2026-08-21") is not None


# --- FR-3 (кворум) ----------------------------------------------------------


def test_quorum_message_once_without_pings(tmp_path):
    bot, store, service = build(tmp_path)
    run(open_and_vote(service, store, 8))

    texts = bot.texts()
    assert len(texts) == 1
    assert "Кворум" in texts[0]
    assert "@" not in texts[0] and "tg://" not in texts[0]


def test_ninth_plus_does_not_repeat_quorum(tmp_path):
    bot, store, service = build(tmp_path)
    run(open_and_vote(service, store, 9))
    assert len(bot.texts()) == 1


def test_seven_plus_stays_silent(tmp_path):
    bot, store, service = build(tmp_path)
    run(open_and_vote(service, store, 7))
    assert bot.texts() == []


def test_minus_votes_never_trigger_anything(tmp_path):
    bot, store, service = build(tmp_path)
    run(open_and_vote(service, store, 13, option=MINUS))
    assert bot.texts() == []
    assert bot.named("stop_poll") == []


def test_later_votes_never_trigger_anything(tmp_path):
    bot, store, service = build(tmp_path)
    run(open_and_vote(service, store, 12, option=LATER))
    assert bot.texts() == []
    assert bot.named("stop_poll") == []


# --- FR-2 (полный состав) ---------------------------------------------------


def test_twelfth_plus_closes_poll_and_pings_squad(tmp_path):
    bot, store, service = build(tmp_path)
    run(open_and_vote(service, store, 12))

    assert len(bot.named("stop_poll")) == 1
    final = bot.texts()[-1]
    assert "Набор окончен" in final
    assert final.count("@user") == 12
    assert store.poll_for_day("2026-08-21").closed is True


def test_votes_after_close_change_nothing(tmp_path):
    bot, store, service = build(tmp_path)
    poll = run(open_and_vote(service, store, 12))
    run(service.handle_vote(poll.poll_id, voter(13), [PLUS]))
    run(service.handle_vote(poll.poll_id, voter(1), []))

    assert len(bot.named("stop_poll")) == 1
    assert len(bot.texts()) == 2  # кворум + набор окончен, и ничего больше


def test_vote_in_unknown_poll_is_ignored(tmp_path):
    bot, store, service = build(tmp_path)
    run(service.handle_vote("ghost-poll", voter(1), [PLUS]))
    assert bot.calls == []


# --- FR-4 (17:00) -----------------------------------------------------------


def test_closing_with_quorum_says_playing(tmp_path):
    bot, store, service = build(tmp_path)
    poll = run(open_and_vote(service, store, 8))
    run(service.close_poll(store.poll_by_id(poll.poll_id)))

    final = bot.texts()[-1]
    assert "Играем" in final
    assert final.count("@user") == 8
    assert store.poll_by_id(poll.poll_id).closed is True


def test_closing_below_quorum_says_no_game(tmp_path):
    bot, store, service = build(tmp_path)
    poll = run(open_and_vote(service, store, 7))
    bot.plus_voter_count = 7  # Telegram подтверждает: больше плюсов и не было
    run(service.close_poll(store.poll_by_id(poll.poll_id)))

    final = bot.texts()[-1]
    assert "игры сегодня нет" in final
    assert "@" not in final


def test_closing_twice_is_harmless(tmp_path):
    bot, store, service = build(tmp_path)
    poll = run(open_and_vote(service, store, 3))
    run(service.close_poll(store.poll_by_id(poll.poll_id)))
    run(service.close_poll(store.poll_by_id(poll.poll_id)))
    assert len(bot.named("stop_poll")) == 1


# --- SC-4 (потеря прав не должна быть тихой) --------------------------------


def test_failed_close_is_reported_to_the_chat(tmp_path):
    bot, store, service = build(tmp_path, fail_on=("stop_poll",))
    run(open_and_vote(service, store, 12))

    assert any("вручную" in t for t in bot.texts()), "молчаливый провал закрытия недопустим"
    assert store.poll_for_day("2026-08-21").closed is False


def test_failed_close_is_reported_once_not_on_every_vote(tmp_path):
    bot, store, service = build(tmp_path, fail_on=("stop_poll",))
    poll = run(open_and_vote(service, store, 12))
    run(service.handle_vote(poll.poll_id, voter(13), [PLUS]))
    run(service.handle_vote(poll.poll_id, voter(14), [PLUS]))

    assert len([t for t in bot.texts() if "вручную" in t]) == 1


def test_send_poll_failure_does_not_crash_and_stores_nothing(tmp_path):
    bot, store, service = build(tmp_path, fail_on=("send_poll",))
    run(service.open_poll(date(2026, 8, 21)))
    assert store.poll_for_day("2026-08-21") is None


def test_send_message_failure_does_not_crash_the_vote_handler(tmp_path):
    bot, store, service = build(tmp_path, fail_on=("send_message",))
    run(open_and_vote(service, store, 8))
    assert store.poll_for_day("2026-08-21") is not None


# --- /status ----------------------------------------------------------------


def test_status_reports_open_poll(tmp_path):
    bot, store, service = build(tmp_path)
    run(open_and_vote(service, store, 3))
    text = run(service.status_text())
    assert "3" in text


def test_status_without_poll_says_so(tmp_path):
    bot, store, service = build(tmp_path)
    text = run(service.status_text())
    assert "нет" in text.lower()


# --- находки ревью: ложь про закрытие, гонки, авторитетный счёт ---------------


def test_failed_close_never_claims_the_poll_is_closed(tmp_path):
    """Провал stopPoll: группе нельзя говорить «Опрос закрыт» — он открыт и в нём голосуют."""
    bot, store, service = build(tmp_path, fail_on=("stop_poll",))
    poll = run(open_and_vote(service, store, 7))
    run(service.close_poll(store.poll_by_id(poll.poll_id)))

    assert not any("Опрос закрыт" in t for t in bot.texts())
    assert any("вручную" in t for t in bot.texts())
    assert store.poll_by_id(poll.poll_id).closed is False


def test_failed_close_does_not_repeat_itself_on_every_tick(tmp_path):
    bot, store, service = build(tmp_path, fail_on=("stop_poll",))
    poll = run(open_and_vote(service, store, 7))
    for _ in range(3):
        run(service.close_poll(store.poll_by_id(poll.poll_id)))

    assert len(bot.texts()) == 1, "три тика не должны давать три сообщения"


def test_closing_trusts_telegrams_count_over_its_own(tmp_path):
    """Голоса, потерянные во время простоя, не должны превращаться в «игры нет»."""
    bot, store, service = build(tmp_path)
    poll = run(open_and_vote(service, store, 3))
    bot.plus_voter_count = 9  # столько плюсов на самом деле в опросе
    run(service.close_poll(store.poll_by_id(poll.poll_id)))

    final = bot.texts()[-1]
    assert "Играем" in final
    assert "9" in final


def test_concurrent_votes_announce_quorum_once(tmp_path):
    bot, store, service = build(tmp_path)
    bot.delay = 0.05  # ответ Telegram не мгновенный: окно для гонки открыто
    poll = run(open_and_vote(service, store, 7))

    async def two_at_once():
        await asyncio.gather(
            service.handle_vote(poll.poll_id, voter(8), [PLUS]),
            service.handle_vote(poll.poll_id, voter(9), [PLUS]),
        )

    run(two_at_once())
    assert len([t for t in bot.texts() if "Кворум" in t]) == 1


def test_concurrent_full_squad_closes_once(tmp_path):
    bot, store, service = build(tmp_path)
    bot.delay = 0.05
    poll = run(open_and_vote(service, store, 11))

    async def two_at_once():
        await asyncio.gather(
            service.handle_vote(poll.poll_id, voter(12), [PLUS]),
            service.handle_vote(poll.poll_id, voter(13), [PLUS]),
        )

    run(two_at_once())
    assert len(bot.named("stop_poll")) == 1
    assert len([t for t in bot.texts() if "Набор окончен" in t]) == 1


def test_concurrent_open_poll_posts_one_poll(tmp_path):
    """Тик при старте и cron в 09:00 могут прийти одновременно."""
    bot, store, service = build(tmp_path)
    bot.delay = 0.05

    async def two_at_once():
        await asyncio.gather(
            service.open_poll(date(2026, 8, 21)),
            service.open_poll(date(2026, 8, 21)),
        )

    run(two_at_once())
    assert len(bot.named("send_poll")) == 1
    assert len(bot.named("pin_chat_message")) == 1


# --- находки круга 2: тишина вместо предупреждения, потерянный итог ----------


def test_warning_is_retried_while_it_cannot_be_delivered(tmp_path):
    """Если и предупреждение не ушло, помечать «уже сказали» нельзя — будет тишина."""
    bot, store, service = build(tmp_path, fail_on=("stop_poll", "send_message"))
    poll = run(open_and_vote(service, store, 12))
    assert store.poll_by_id(poll.poll_id).close_error_notified is False

    bot.fail_on = ("stop_poll",)  # чат снова доступен
    run(service.handle_vote(poll.poll_id, voter(13), [PLUS]))
    assert any("вручную" in t for t in bot.texts())


def test_poll_closed_by_hand_is_not_reported_as_missing_rights(tmp_path):
    """Админ закрыл опрос сам — это не ошибка прав, итог всё равно нужен."""
    bot, store, service = build(tmp_path)
    poll = run(open_and_vote(service, store, 8))
    bot.fail_on = ("stop_poll",)
    bot.stop_poll_error = "Bad Request: poll has already been closed"
    run(service.close_poll(store.poll_by_id(poll.poll_id)))

    final = bot.texts()[-1]
    assert "Играем" in final
    assert not any("прав" in t for t in bot.texts())
    assert store.poll_by_id(poll.poll_id).closed is True


def test_outcome_survives_a_failed_first_announcement(tmp_path):
    """stopPoll прошёл, а сообщение не ушло: итог не должен потеряться навсегда."""
    bot, store, service = build(tmp_path, fail_on=("send_message",))
    poll = run(open_and_vote(service, store, 8))
    run(service.close_poll(store.poll_by_id(poll.poll_id)))
    assert store.poll_by_id(poll.poll_id).closed is False, "итог не опубликован — не закрываем учёт"

    bot.fail_on = ()
    bot.stop_poll_error = "Bad Request: poll has already been closed"
    run(service.close_poll(store.poll_by_id(poll.poll_id)))

    assert any("Играем" in t for t in bot.texts())
    assert store.poll_by_id(poll.poll_id).closed is True


def test_squad_message_failure_keeps_the_poll_open_in_the_ledger(tmp_path):
    """Состав не объявлен — значит закрытие не доведено до конца, попробуем ещё."""
    bot, store, service = build(tmp_path, fail_on=("send_message",))
    poll = run(open_and_vote(service, store, 12))
    assert store.poll_by_id(poll.poll_id).closed is False


def test_retry_keeps_the_count_telegram_gave_at_first_close(tmp_path):
    """Счёт Telegram нельзя терять между попытками: иначе игра «отменяется» задним числом."""
    bot, store, service = build(tmp_path, fail_on=("send_message",))
    poll = run(open_and_vote(service, store, 3))
    bot.plus_voter_count = 9  # столько плюсов видит Telegram
    run(service.close_poll(store.poll_by_id(poll.poll_id)))
    assert store.poll_by_id(poll.poll_id).closed is False

    bot.fail_on = ()
    bot.stop_poll_error = "Bad Request: poll has already been closed"
    bot.fail_on = ("stop_poll",)  # опрос уже закрыт, счётчиков больше не дадут
    run(service.close_poll(store.poll_by_id(poll.poll_id)))

    final = bot.texts()[-1]
    assert "Играем" in final and "9" in final
    assert "нет" not in final.lower()


def test_manual_close_without_counts_never_cancels_the_game_outright(tmp_path):
    """Админ закрыл опрос сам, счётчиков не дали — «игры нет» утверждать нельзя."""
    bot, store, service = build(tmp_path)
    poll = run(open_and_vote(service, store, 3))
    bot.fail_on = ("stop_poll",)
    bot.stop_poll_error = "Bad Request: poll has already been closed"
    run(service.close_poll(store.poll_by_id(poll.poll_id)))

    final = bot.texts()[-1]
    assert "игры сегодня нет" not in final
    assert store.poll_by_id(poll.poll_id).closed is True


# --- напоминание тем, кто обещал ответ к 16-00 ------------------------------


def test_reminder_pings_only_those_who_promised_an_answer(tmp_path):
    bot, store, service = build(tmp_path)
    run(service.open_poll(date(2026, 8, 21)))
    poll = store.poll_for_day("2026-08-21")
    run(service.handle_vote(poll.poll_id, voter(1), [PLUS]))
    run(service.handle_vote(poll.poll_id, voter(2), [MINUS]))
    run(service.handle_vote(poll.poll_id, voter(3), [LATER]))

    run(service.remind_later(store.poll_by_id(poll.poll_id)))

    (text,) = bot.texts()
    assert "@user3" in text
    assert "@user1" not in text and "@user2" not in text


def test_no_reminder_when_nobody_promised(tmp_path):
    bot, store, service = build(tmp_path)
    poll = run(open_and_vote(service, store, 3))
    run(service.remind_later(store.poll_by_id(poll.poll_id)))
    assert bot.texts() == []


def test_no_reminder_in_a_closed_poll(tmp_path):
    bot, store, service = build(tmp_path)
    run(service.open_poll(date(2026, 8, 21)))
    poll = store.poll_for_day("2026-08-21")
    run(service.handle_vote(poll.poll_id, voter(3), [LATER]))
    store.mark_closed(poll.poll_id)

    run(service.remind_later(store.poll_by_id(poll.poll_id)))
    assert bot.texts() == []


def test_reminder_without_a_poll_is_harmless(tmp_path):
    bot, store, service = build(tmp_path)
    run(service.remind_later(None))
    assert bot.calls == []


def test_failed_poll_creation_stays_out_of_the_group(tmp_path):
    """Нет прав или сбой сети — это в лог. Отсутствие опроса группа увидит сама."""
    bot, store, service = build(tmp_path, fail_on=("send_poll",))
    run(service.open_poll(date(2026, 8, 21)))

    assert bot.texts() == []
    assert store.poll_for_day("2026-08-21") is None
