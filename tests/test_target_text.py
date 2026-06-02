"""Tests for speech.target_text (CLIP spoken-target refinement)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from speech.target_text import refine_clip_query_text, refine_parsed_voice_query


def test_korean_ui_maps():
    assert refine_clip_query_text("이 항목을 목록에 고정") == "pin"
    assert refine_clip_query_text("기타 옵션") == "more options"
    assert refine_clip_query_text("클릭하여 kt 팔로우") == "follow"


def test_shortcut_strip():
    assert refine_clip_query_text("settings and more (alt+f)") == "settings"
    assert refine_clip_query_text("add this page to favorites (ctrl+d)") == "favorites"


def test_keeps_short_targets():
    assert refine_clip_query_text("search") == "search"
    assert refine_clip_query_text("close") == "close"
    assert refine_clip_query_text("논현일보") == "논현일보"


def test_voice_light_pass():
    assert refine_parsed_voice_query("  Close  ") == "close"
    assert refine_parsed_voice_query("settings") == "settings"


if __name__ == "__main__":
    import unittest

    unittest.main()
