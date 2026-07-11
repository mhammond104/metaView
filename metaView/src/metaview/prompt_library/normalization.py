"""Prompt text normalisation helpers.

The Prompt Library uses a normalised key for exact-prompt matching. The original
prompt text is always retained for display and editing.
"""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")


def normalize_prompt(prompt: str) -> str:
    """Return a stable exact-match key for *prompt*.

    Leading and trailing whitespace is removed and every internal run of
    whitespace (including line breaks and tabs) is collapsed to one ASCII
    space. Letter case and punctuation are deliberately preserved.
    """

    if not isinstance(prompt, str):
        raise TypeError("prompt must be a string")
    return _WHITESPACE.sub(" ", prompt.strip())
