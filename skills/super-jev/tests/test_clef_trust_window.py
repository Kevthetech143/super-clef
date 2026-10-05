#!/usr/bin/env python3
"""Clef trust window: a pick at or above CLEF_TRUST_MIN (0.9) is trusted; under it is low trust.
Made-up probabilities, stub judge, no network. Band measured on DEV data only (calibration REPORT finding 2).

    python3 -m pytest skills/super-jev/tests/test_clef_trust_window.py -q
"""
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(SKILL), str(SKILL / "lib")]
import judges  # noqa: E402
import ask  # noqa: E402


def _reply(prob):
    return {"answers": {"pick": {"type": "choice", "choice": "file_1", "confidence": prob,
                                 "probabilities": {"file_1": prob, "file_2": round(1 - prob, 4), "none": 0.0}}},
            "model": "clef-flash", "usage": {"input_tokens": 600}}


@pytest.mark.parametrize("prob,low", [(0.72, True), (0.85, True), (0.899, True), (0.9, False), (0.93, False), (0.99, False)])
def test_trust_window(tmp_path, monkeypatch, prob, low):
    monkeypatch.setattr(ask, "CLEF", True)
    monkeypatch.setitem(ask._CLEF, "low_trust", set())
    fs = []
    for i in range(2):
        f = tmp_path / f"note{i}.md"
        f.write_text("The orchid greenhouse opens at 9am. Orchid watering is on Mondays.")
        fs.append(str(f))
    monkeypatch.setattr(judges, "ask", lambda s, q, timeout=0: _reply(prob))
    scores, _, _, _ = ask.clef_confirm("orchid greenhouse opens", fs)
    (p,) = scores
    assert (p in ask._CLEF["low_trust"]) is low


def test_band_constant():
    assert ask.CLEF_TRUST_MIN == 0.9
