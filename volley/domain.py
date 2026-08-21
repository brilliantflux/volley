"""Чистая логика опроса: подсчёт голосов и решения. Без Telegram и без БД."""

from __future__ import annotations

from dataclasses import dataclass, field

PLUS, MINUS, LATER = 0, 1, 2

QUORUM = 8  # столько плюсов — игра точно состоится
FULL_SQUAD = 12  # две команды по шесть, замен нет


@dataclass(frozen=True)
class Voter:
    user_id: int
    first_name: str
    username: str | None = None


@dataclass
class Poll:
    """Опрос одного дня вместе с текущими голосами."""

    day: str  # ISO-дата дня игры
    poll_id: str
    message_id: int
    closed: bool = False
    quorum_announced: bool = False
    close_error_notified: bool = False
    telegram_plus_count: int | None = None  # счёт, который Telegram дал при закрытии
    votes: dict[int, tuple[int, Voter]] = field(default_factory=dict)

    def apply(self, voter: Voter, option_ids: list[int]) -> None:
        """Голос из poll_answer. Пустой option_ids означает отозванный голос."""
        if not option_ids:
            self.votes.pop(voter.user_id, None)
        else:
            self.votes[voter.user_id] = (option_ids[0], voter)

    def voters_for(self, option: int) -> list[Voter]:
        return [voter for chosen, voter in self.votes.values() if chosen == option]

    @property
    def plus(self) -> list[Voter]:
        return self.voters_for(PLUS)

    @property
    def later(self) -> list[Voter]:
        return self.voters_for(LATER)


@dataclass(frozen=True)
class Outcome:
    playing: bool
    plus: list[Voter]
    count: int | None = None  # сколько плюсов насчитал Telegram, если он ответил

    @property
    def total(self) -> int:
        """Плюсов на самом деле: счёт Telegram важнее нашего, если он известен."""
        return len(self.plus) if self.count is None else self.count


def decide_after_vote(
    poll: Poll, quorum: int = QUORUM, full: int = FULL_SQUAD
) -> tuple[str, ...]:
    """Что делать после очередного голоса: ('quorum',), ('close_full',) или ничего.

    Кворум объявляется один раз за день: голос можно отозвать и поставить снова,
    и группа не должна получать «кворум есть» по второму кругу. Скачок сразу до
    полного состава даёт только «набор окончен» — без дубля про кворум.
    """
    if poll.closed:
        return ()
    count = len(poll.plus)
    if count >= full:
        return ("close_full",)
    if count >= quorum and not poll.quorum_announced:
        return ("quorum",)
    return ()


def daily_outcome(
    poll: Poll, quorum: int = QUORUM, plus_count: int | None = None
) -> Outcome:
    plus = poll.plus
    total = len(plus) if plus_count is None else plus_count
    return Outcome(playing=total >= quorum, plus=plus, count=plus_count)
