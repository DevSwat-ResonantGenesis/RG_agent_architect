"""Tests for mode_classifier"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.prompts.mode_classifier import classify_mode
from src.models.agent import OperationMode

def test_brainstorm(): assert classify_mode("what can you do?", False) == OperationMode.BRAINSTORM
def test_control(): assert classify_mode("build a scraper", True) == OperationMode.CONTROL
def test_review(): assert classify_mode("what happened with results?", True) == OperationMode.REVIEW
def test_ambiguous_agents(): assert classify_mode("hello", True) == OperationMode.CONTROL
def test_ambiguous_no_agents(): assert classify_mode("hello", False) == OperationMode.BRAINSTORM
