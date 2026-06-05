"""Unit tests for the in-memory rate limiter (app.auth.rate_limit)."""

from __future__ import annotations

from app.auth import rate_limit as rl


def test_fixed_window_blocks_after_limit():
    rl.reset()
    key = "1.2.3.4"
    # 3 allowed in the window, the 4th is blocked.
    for _ in range(3):
        ok, _retry = rl._check("test", key, times=3, seconds=60)
        assert ok is True
    ok, retry = rl._check("test", key, times=3, seconds=60)
    assert ok is False
    assert retry >= 1


def test_different_keys_are_independent():
    rl.reset()
    ok_a, _ = rl._check("b", "a", times=1, seconds=60)
    ok_b, _ = rl._check("b", "b", times=1, seconds=60)
    assert ok_a is True and ok_b is True


def test_expired_hits_are_evicted():
    rl.reset()
    ok, _ = rl._check("w", "k", times=1, seconds=0)  # window 0 → always allows
    assert ok is True
    ok2, _ = rl._check("w", "k", times=1, seconds=0)
    assert ok2 is True
