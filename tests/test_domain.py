"""SC-1: подсчёт голосов и решения при смене и отзыве голоса."""

from volley.domain import (
    LATER,
    MINUS,
    PLUS,
    Poll,
    Voter,
    daily_outcome,
    decide_after_vote,
)


def make_poll(**kw) -> Poll:
    return Poll(day="2026-08-21", poll_id="p1", message_id=10, **kw)


def voter(n: int) -> Voter:
    return Voter(user_id=n, first_name=f"Игрок{n}", username=f"user{n}")


def vote(poll: Poll, n: int, option: int) -> None:
    poll.apply(voter(n), [option])


def fill_plus(poll: Poll, count: int, start: int = 1) -> None:
    for n in range(start, start + count):
        vote(poll, n, PLUS)


def test_plus_counted():
    poll = make_poll()
    fill_plus(poll, 3)
    assert [v.user_id for v in poll.plus] == [1, 2, 3]


def test_revote_moves_user_between_options():
    poll = make_poll()
    vote(poll, 1, MINUS)
    vote(poll, 1, PLUS)
    assert [v.user_id for v in poll.plus] == [1]
    assert poll.voters_for(MINUS) == []


def test_retract_removes_vote():
    poll = make_poll()
    vote(poll, 1, PLUS)
    poll.apply(voter(1), [])
    assert poll.plus == []


def test_later_voters_listed_separately():
    poll = make_poll()
    vote(poll, 1, LATER)
    vote(poll, 2, PLUS)
    assert [v.user_id for v in poll.later] == [1]
    assert [v.user_id for v in poll.plus] == [2]


def test_quorum_announced_at_eight():
    poll = make_poll()
    fill_plus(poll, 8)
    assert decide_after_vote(poll) == ("quorum",)


def test_quorum_not_repeated():
    poll = make_poll(quorum_announced=True)
    fill_plus(poll, 9)
    assert decide_after_vote(poll) == ()


def test_drop_below_quorum_and_back_does_not_reannounce():
    poll = make_poll()
    fill_plus(poll, 8)
    assert decide_after_vote(poll) == ("quorum",)
    poll.quorum_announced = True
    poll.apply(voter(8), [])
    assert decide_after_vote(poll) == ()
    vote(poll, 8, PLUS)
    assert decide_after_vote(poll) == ()


def test_full_squad_closes():
    poll = make_poll(quorum_announced=True)
    fill_plus(poll, 12)
    assert decide_after_vote(poll) == ("close_full",)


def test_twelfth_plus_does_not_also_announce_quorum():
    """Скачок с 7 до 12 без объявленного кворума: только «набор окончен», без дубля."""
    poll = make_poll()
    fill_plus(poll, 12)
    assert decide_after_vote(poll) == ("close_full",)


def test_closed_poll_yields_no_decisions():
    poll = make_poll(closed=True)
    fill_plus(poll, 12)
    assert decide_after_vote(poll) == ()


def test_minus_votes_do_not_count_towards_squad():
    poll = make_poll()
    fill_plus(poll, 7)
    for n in range(8, 20):
        vote(poll, n, MINUS)
    assert decide_after_vote(poll) == ()


def test_outcome_playing_at_quorum():
    poll = make_poll()
    fill_plus(poll, 8)
    outcome = daily_outcome(poll)
    assert outcome.playing is True
    assert len(outcome.plus) == 8


def test_outcome_not_playing_one_short_of_quorum():
    poll = make_poll()
    fill_plus(poll, 7)
    assert daily_outcome(poll).playing is False


def test_outcome_not_playing_with_zero_plus():
    """17 августа так и было: ноль плюсов, тринадцать минусов."""
    poll = make_poll()
    for n in range(1, 14):
        vote(poll, n, MINUS)
    assert daily_outcome(poll).playing is False
    assert daily_outcome(poll).plus == []
