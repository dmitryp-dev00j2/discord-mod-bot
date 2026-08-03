import time
import pytest
from modbot.rules import check_mentions, check_invite_links, clean_text, SlidingWindow


def test_mention_count():
    content_ok = "Hey <@12345> and <@67890> check this out"
    assert check_mentions(content_ok, max_mentions=3) is False

    content_bad = "<@1> <@2> <@3> <@4> wake up!"
    assert check_mentions(content_bad, max_mentions=3) is True

    content_roles = "<@&111> <@&222> <@&333>"
    assert check_mentions(content_roles, max_mentions=2) is True


def test_invite_regex():
    assert check_invite_links("join my server discord.gg/abcdef") is True
    assert check_invite_links("discord.com/invite/xyz123") is True
    assert check_invite_links("DISCORD.GG/TEST") is True
    assert check_invite_links("check https://google.com nothing here") is False


def test_invite_obfuscation():
    # zero-width spaces inserted between characters to trick naive regexes
    hidden = "d\u200biscord.gg/\u200chax123"
    cleaned = clean_text(hidden)
    assert check_invite_links(cleaned) is True


def test_sliding_window_burst():
    tracker = SlidingWindow(limit=3, window_seconds=2)
    uid = 999

    now = time.time()
    assert tracker.add_hit(uid, now=now) is False
    assert tracker.add_hit(uid, now=now + 0.1) is False
    assert tracker.add_hit(uid, now=now + 0.2) is False
    # 4th hit in the same second triggers rate limit
    assert tracker.add_hit(uid, now=now + 0.3) is True

    # hits after window expiry should reset count
    assert tracker.add_hit(uid, now=now + 2.5) is False
    assert tracker.count_hits(uid, now=now + 2.5) == 1
