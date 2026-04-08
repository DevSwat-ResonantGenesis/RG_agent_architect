"""Tests for goal_crafter — Twin 8-step pipeline (twin.md lines 399-408)."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.goal_crafter import craft_goal, ScopeRisk


def test_strip_recurrence():
    """twin.md line 402: Strip time/recurrence language from goal."""
    result = craft_goal("Search for new leads daily and email them")
    assert result.schedule is not None
    assert "daily" not in result.goal_text.lower() or result.schedule == "daily"


def test_strip_secrets():
    """twin.md line 403: Never include secrets in goal text."""
    result = craft_goal("Monitor API using api_key=sk-12345 for errors")
    assert "sk-12345" not in result.goal_text
    assert result.secrets_redacted is True


def test_high_risk_all_companies():
    """twin.md lines 412-417: Entity discovery = HIGH risk."""
    result = craft_goal("Find all companies in the US that need marketing")
    assert result.risk_level == ScopeRisk.HIGH


def test_high_risk_scrape_all():
    result = craft_goal("Scrape all restaurant listings in New York")
    assert result.risk_level == ScopeRisk.HIGH


def test_moderate_risk():
    result = craft_goal("Find companies in Austin without a website")
    assert result.risk_level == ScopeRisk.MODERATE


def test_safe_risk():
    """twin.md lines 421-424: Single API call, small bounds = SAFE."""
    result = craft_goal("Search for the top 10 AI startups")
    assert result.risk_level == ScopeRisk.SAFE


def test_identify_services():
    result = craft_goal("Search LinkedIn for recruiters and email them", ["web_search", "scrape_platforms", "send_email"])
    assert "scrape_platforms" in result.services or "send_email" in result.services


def test_smart_defaults_no_number():
    """Add default bounds when no explicit limit in goal."""
    result = craft_goal("Find AI companies hiring remotely")
    assert any("15" in a for a in result.assumptions)


def test_preserves_original():
    raw = "Monitor stock prices daily for AAPL"
    result = craft_goal(raw)
    assert result.original_text == raw
