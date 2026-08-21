"""Тексты для группы: теги там, где нужны пинги, и никогда — где не нужны."""

from datetime import date

from volley import texts
from volley.domain import Outcome, Poll, Voter

WITH_USERNAME = Voter(user_id=1, first_name="Первый", username="player1")
NO_USERNAME = Voter(user_id=2, first_name="Второй", username=None)
TRICKY = Voter(user_id=3, first_name="<Третий> & Co", username=None)


def test_mention_uses_username_when_present():
    assert texts.mention(WITH_USERNAME) == "@player1"


def test_mention_without_username_falls_back_to_tg_link():
    assert texts.mention(NO_USERNAME) == '<a href="tg://user?id=2">Второй</a>'


def test_mention_escapes_html_in_name():
    assert texts.mention(TRICKY) == '<a href="tg://user?id=3">&lt;Третий&gt; &amp; Co</a>'


def test_plain_name_escapes_html_and_never_pings():
    plain = texts.plain_name(TRICKY)
    assert plain == "&lt;Третий&gt; &amp; Co"
    assert "@" not in plain and "tg://" not in plain


def test_poll_question_has_date_weekday_and_game_time():
    assert texts.poll_question(date(2026, 8, 21)) == "21.08 (пт) Игра 18-00"


def test_poll_options_match_the_group_habit():
    assert texts.POLL_OPTIONS == ("Плюс", "Минус", "Ответ до 16-00")


def test_quorum_text_lists_names_without_pinging_anyone():
    text = texts.quorum_text([WITH_USERNAME, NO_USERNAME])
    assert "Первый" in text and "Второй" in text
    assert "@" not in text and "tg://" not in text


def test_squad_full_text_pings_the_squad():
    text = texts.squad_full_text([WITH_USERNAME, NO_USERNAME])
    assert "@player1" in text
    assert 'tg://user?id=2' in text


def test_closing_text_playing_pings_the_squad():
    text = texts.closing_text(Outcome(playing=True, plus=[WITH_USERNAME, NO_USERNAME]))
    assert "@player1" in text
    assert "2" in text


def test_closing_text_not_playing_says_so_and_pings_nobody():
    text = texts.closing_text(Outcome(playing=False, plus=[WITH_USERNAME], count=1))
    assert "игры сегодня нет" in text
    assert "@" not in text and "tg://" not in text


def test_status_text_reports_counts():
    poll = Poll(day="2026-08-21", poll_id="p", message_id=1)
    poll.apply(WITH_USERNAME, [0])
    poll.apply(NO_USERNAME, [2])
    text = texts.status_text(poll)
    assert "21.08" in text, "дата в человеческом формате, как в самом опросе"
    assert "1" in text
    assert "@" not in text and "tg://" not in text


def test_error_text_names_the_action_and_asks_for_hands():
    text = texts.error_text("закрыть опрос", "Forbidden: not enough rights")
    assert "закрыть опрос" in text
    assert "Forbidden" in text
    assert "вручную" in text


def test_no_game_is_stated_plainly_when_the_count_is_authoritative():
    text = texts.closing_text(Outcome(playing=False, plus=[WITH_USERNAME], count=2))
    assert "игры сегодня нет" in text


def test_no_game_is_hedged_when_the_count_is_only_ours():
    """Своих голосов может быть меньше реальных: категоричное «нет» тут — вранье."""
    text = texts.closing_text(Outcome(playing=False, plus=[WITH_USERNAME], count=None))
    assert "игры сегодня нет" not in text
    assert "опрос" in text.lower()


def test_playing_needs_no_hedge_even_on_our_own_count():
    """Восемь своих плюсов означают минимум восемь реальных — вывод безопасен."""
    text = texts.closing_text(Outcome(playing=True, plus=[WITH_USERNAME, NO_USERNAME], count=None))
    assert "Играем" in text
