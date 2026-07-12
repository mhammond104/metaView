"""Canonical normalisation helpers for generation metadata."""
from __future__ import annotations
from typing import Any, Iterable, Mapping

def normalise_prompt(value: str) -> str:
    return " ".join(value.split()).casefold()

def normalise_text(value: Any) -> str:
    return "" if value is None else str(value).strip()

def normalise_lora_name(value: Any) -> str:
    return normalise_text(value).casefold()

def lora_signature(loras: Iterable[Mapping[str, Any]]) -> tuple[tuple[str, str, str], ...]:
    entries = {
        (
            normalise_lora_name(lora.get("name")),
            normalise_text(lora.get("model_strength")),
            normalise_text(lora.get("clip_strength")),
        )
        for lora in loras
        if normalise_lora_name(lora.get("name"))
    }
    return tuple(sorted(entries))
