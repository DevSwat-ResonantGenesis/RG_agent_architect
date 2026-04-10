"""Lightweight safety checks for Architect Orchestrator.

Pattern-based safety without full Agent Engine executor overhead.
Checks for dangerous patterns in tool arguments and LLM responses.
"""
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Critical patterns that should be blocked
CRITICAL_PATTERNS = [
    # System destruction
    r'rm\s+-rf\s+/',
    r'rm\s+-rf\s+\*',
    r':(){ :|:& };:',  # Fork bomb
    r'dd\s+if=/dev/zero',
    r'mkfs\.',  # Filesystem formatting
    r'chmod\s+777\s+/',
    r'chown\s+-R\s+root',
    # Remote code execution
    r'eval\s*\(',
    r'exec\s*\(',
    r'__import__\s*\(',
    r'subprocess\.(call|Popen|run)\s*\(',
    r'os\.system\s*\(',
    r'pickle\.loads\s*\(',
    r'marshal\.loads\s*\(',
    # SQL injection patterns
    r"'\s*OR\s*'1'='1",
    r"'\s*OR\s*1=1",
    r';\s*DROP\s+TABLE',
    r';\s*DELETE\s+FROM',
    r';\s*INSERT\s+INTO',
    r';\s*UPDATE\s+\w+\s+SET',
    # Exfiltration patterns
    r'curl.*http.*\|',
    r'wget.*http.*\|',
    r'nc\s+-l\s+-p',
    r'netcat\s+-l',
    r'ssh.*-R',
    # Sensitive data patterns
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b.*password',
    r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b',  # Credit card
    r'\b[0-9a-fA-F]{32}\b',  # Potential API key
    r'\b[0-9a-fA-F]{40}\b',  # Potential secret
]

# High-risk patterns that should be logged and warned
HIGH_RISK_PATTERNS = [
    r'sudo',
    r'chmod\s+777',
    r'chown',
    r'\.ssh',
    r'\.env',
    r'password',
    r'secret',
    r'api_key',
    r'token',
    r'credential',
]


class LightweightSafety:
    """Pattern-based safety checks for architect orchestrator."""

    def __init__(self):
        self.blocked_count = 0
        self.warned_count = 0

    def check_tool_args(self, tool_name: str, args: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Check tool arguments for dangerous patterns.
        Returns (is_safe, error_message).
        """
        # Convert args to string for pattern matching
        args_str = str(args).lower()
        
        # Check critical patterns
        for pattern in CRITICAL_PATTERNS:
            if re.search(pattern, args_str, re.IGNORECASE):
                self.blocked_count += 1
                logger.warning(
                    f"[SAFETY] Blocked {tool_name} - matched critical pattern: {pattern}"
                )
                return False, f"Blocked: dangerous pattern detected in arguments"
        
        # Check high-risk patterns (log but don't block)
        for pattern in HIGH_RISK_PATTERNS:
            if re.search(pattern, args_str, re.IGNORECASE):
                self.warned_count += 1
                logger.warning(
                    f"[SAFETY] Warning on {tool_name} - matched high-risk pattern: {pattern}"
                )
        
        return True, None

    def check_llm_response(self, content: str) -> tuple[bool, Optional[str]]:
        """
        Check LLM response for dangerous patterns.
        Returns (is_safe, error_message).
        """
        content_lower = content.lower()
        
        # Check critical patterns
        for pattern in CRITICAL_PATTERNS:
            if re.search(pattern, content_lower, re.IGNORECASE):
                self.blocked_count += 1
                logger.warning(
                    f"[SAFETY] Blocked LLM response - matched critical pattern: {pattern}"
                )
                return False, f"Blocked: dangerous pattern detected in response"
        
        # Check high-risk patterns
        for pattern in HIGH_RISK_PATTERNS:
            if re.search(pattern, content_lower, re.IGNORECASE):
                self.warned_count += 1
                logger.warning(
                    f"[SAFETY] Warning on LLM response - matched high-risk pattern: {pattern}"
                )
        
        return True, None

    def get_stats(self) -> Dict[str, int]:
        """Get safety statistics."""
        return {
            "blocked_count": self.blocked_count,
            "warned_count": self.warned_count,
        }


# Global safety instance
_safety_instance = Optional[LightweightSafety]


def get_safety() -> LightweightSafety:
    """Get or create the global safety instance."""
    global _safety_instance
    if _safety_instance is None:
        _safety_instance = LightweightSafety()
    return _safety_instance
