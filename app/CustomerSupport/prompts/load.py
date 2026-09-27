from pathlib import Path

_SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "system.md"


def load_system_prompt() -> str:
    """Read the customer support system prompt from prompts/system.md."""
    return _SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
