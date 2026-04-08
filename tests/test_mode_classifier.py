"""Tests for mode_classifier — Twin mode_classification (twin.md lines 369-373)."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.mode_classifier import classify_mode, OperationMode


def test_brainstorm_signals():
    assert classify_mode("what can you do for me?", False) == OperationMode.BRAINSTORM
    assert classify_mode("help me automate something", False) == OperationMode.BRAINSTORM
    assert classify_mode("I have some ideas for agents", False) == OperationMode.BRAINSTORM


def test_control_signals():
    assert classify_mode("build an agent that monitors prices", True) == OperationMode.CONTROL
    assert classify_mode("create a scraper for LinkedIn", True) == OperationMode.CONTROL
    assert classify_mode("run the email agent", True) == OperationMode.CONTROL
    assert classify_mode("schedule agent daily", True) == OperationMode.CONTROL
    assert classify_mode("delete the old agent", True) == OperationMode.CONTROL


def test_review_signals():
    assert classify_mode("what happened with the last run?", True) == OperationMode.REVIEW
    assert classify_mode("show me the results", True) == OperationMode.REVIEW
    assert classify_mode("how much credits did it cost?", True) == OperationMode.REVIEW
    assert classify_mode("why did it fail?", True) == OperationMode.REVIEW


def test_ambiguous_with_agents():
    """twin.md line 373: When ambiguous, default to Control if agents exist."""
    assert classify_mode("hello there", True) == OperationMode.CONTROL


def test_ambiguous_without_agents():
    """twin.md line 373: When ambiguous, default to Brainstorm if no agents."""
    assert classify_mode("hello there", False) == OperationMode.BRAINSTORM


def test_control_overrides_brainstorm_when_specific():
    """Control beats Brainstorm when message has concrete action words."""
    assert classify_mode("help me build an email scraper", True) == OperationMode.CONTROL
