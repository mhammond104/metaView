"""Headless ComfyUI metadata parsing and normalisation primitives."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

def parse_json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def read_image_metadata(path: Path) -> dict[str, Any]:
    try:
        with Image.open(path) as image:
            metadata = dict(image.info)
    except (OSError, UnidentifiedImageError):
        return {}

    result: dict[str, Any] = {}
    for key, value in metadata.items():
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        result[key] = parse_json_value(value)
    return result


def resolve_node(prompt: dict[str, Any], link: Any) -> dict[str, Any] | None:
    if not isinstance(link, list) or not link:
        return None
    node = prompt.get(str(link[0]))
    return node if isinstance(node, dict) else None


def node_text(
    prompt: dict[str, Any],
    node: dict[str, Any] | None,
    visited: set[str] | None = None,
) -> str:
    if not node:
        return ""
    if visited is None:
        visited = set()

    node_key = str(id(node))
    if node_key in visited:
        return ""
    visited.add(node_key)

    inputs = node.get("inputs", {})
    if not isinstance(inputs, dict):
        return ""

    for key in (
        "text", "prompt", "positive", "negative", "string", "value",
        "text_a", "text_b",
    ):
        value = inputs.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, list):
            text = node_text(prompt, resolve_node(prompt, value), visited)
            if text:
                return text
    return ""


def find_sampler(prompt: dict[str, Any]) -> dict[str, Any] | None:
    preferred = {"KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerCustomAdvanced"}
    for node in prompt.values():
        if isinstance(node, dict) and node.get("class_type") in preferred:
            return node
    for node in prompt.values():
        if isinstance(node, dict) and "sampler" in str(node.get("class_type", "")).lower():
            return node
    return None


def find_model(prompt: dict[str, Any]) -> str:
    for node in prompt.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        for key in ("ckpt_name", "unet_name", "model_name", "checkpoint"):
            value = inputs.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def extract_summary(metadata: dict[str, Any]) -> dict[str, str]:
    empty = {
        "positive": "", "negative": "", "model": "", "seed": "",
        "steps": "", "cfg": "", "sampler": "", "scheduler": "",
        "denoise": "",
    }
    prompt = parse_json_value(metadata.get("prompt"))
    if not isinstance(prompt, dict):
        return empty

    sampler = find_sampler(prompt)
    inputs = sampler.get("inputs", {}) if isinstance(sampler, dict) else {}
    if not isinstance(inputs, dict):
        inputs = {}

    def simple_value(*keys: str) -> str:
        for key in keys:
            value = inputs.get(key)
            if value is not None and not isinstance(value, list):
                return str(value)
        return ""

    return {
        "positive": node_text(prompt, resolve_node(prompt, inputs.get("positive"))),
        "negative": node_text(prompt, resolve_node(prompt, inputs.get("negative"))),
        "model": find_model(prompt),
        "seed": simple_value("seed", "noise_seed"),
        "steps": simple_value("steps"),
        "cfg": simple_value("cfg", "cfg_scale"),
        "sampler": simple_value("sampler_name", "sampler"),
        "scheduler": simple_value("scheduler"),
        "denoise": simple_value("denoise"),
    }


def _format_strength(value: Any) -> str:
    """Format a LoRA strength without unnecessary trailing zeroes."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        return f"{value:g}"
    if isinstance(value, str):
        return value.strip()
    return str(value)


def _looks_like_lora_filename(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.casefold()
    return (
        "lora" in lowered
        or lowered.endswith((".safetensors", ".ckpt", ".pt", ".pth"))
    )


def extract_loras(metadata: dict[str, Any]) -> list[dict[str, str]]:
    """
    Extract LoRA names and strengths from common ComfyUI prompt nodes.

    Handles standard LoraLoader variants and common custom loaders whose
    inputs contain nested LoRA definitions.
    """
    prompt = parse_json_value(metadata.get("prompt"))
    if not isinstance(prompt, dict):
        return []

    results: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def add_lora(name: Any, model_strength: Any = None, clip_strength: Any = None) -> None:
        if not isinstance(name, str) or not name.strip():
            return

        clean_name = name.strip()
        model_text = _format_strength(model_strength)
        clip_text = _format_strength(clip_strength)

        key = (clean_name, model_text, clip_text)
        if key in seen:
            return

        seen.add(key)
        results.append(
            {
                "name": clean_name,
                "model_strength": model_text,
                "clip_strength": clip_text,
            }
        )

    name_keys = (
        "lora_name",
        "lora",
        "lora_file",
        "lora_path",
        "lora_model",
    )
    model_strength_keys = (
        "strength_model",
        "model_strength",
        "strength",
        "weight",
        "lora_strength",
    )
    clip_strength_keys = (
        "strength_clip",
        "clip_strength",
    )

    def first_scalar(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
        for key in keys:
            value = mapping.get(key)
            if value is not None and not isinstance(value, (dict, list)):
                return value
        return None

    def inspect_nested(value: Any) -> None:
        if isinstance(value, dict):
            enabled = value.get("on", value.get("enabled", value.get("active", True)))
            if enabled is False:
                return

            name = first_scalar(value, name_keys + ("name", "filename",))
            if _looks_like_lora_filename(name):
                add_lora(
                    name,
                    first_scalar(value, model_strength_keys),
                    first_scalar(value, clip_strength_keys),
                )

            for nested_value in value.values():
                inspect_nested(nested_value)

        elif isinstance(value, list):
            for nested_value in value:
                inspect_nested(nested_value)

    for node in prompt.values():
        if not isinstance(node, dict):
            continue

        class_type = str(node.get("class_type", ""))
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue

        class_is_lora = "lora" in class_type.casefold()

        direct_name = first_scalar(inputs, name_keys)
        if class_is_lora and isinstance(direct_name, str):
            add_lora(
                direct_name,
                first_scalar(inputs, model_strength_keys),
                first_scalar(inputs, clip_strength_keys),
            )

        # Custom loaders often store one or more LoRAs inside nested mappings
        # such as lora_1, lora_2, loras, or stack entries.
        if class_is_lora:
            inspect_nested(inputs)
        else:
            for key, value in inputs.items():
                if "lora" in key.casefold():
                    inspect_nested(value)

    return results


