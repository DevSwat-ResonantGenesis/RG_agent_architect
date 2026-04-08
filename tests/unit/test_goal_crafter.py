"""Tests for goal_crafter"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.orchestrator.goal_crafter import craft_goal, ScopeRisk

def test_safe(): assert craft_goal("search top 10 AI startups", ["web_search"]).risk_level == ScopeRisk.SAFE
def test_high(): assert craft_goal("scrape all companies in the US", ["web_search"]).risk_level == ScopeRisk.HIGH
def test_moderate(): assert craft_goal("companies in Austin without a website", ["web_search"]).risk_level == ScopeRisk.MODERATE
def test_recurrence():
    r = craft_goal("check prices daily", ["web_search"])
    assert r.schedule is not None
