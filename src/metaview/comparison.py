"""Reusable metadata and LoRA comparison services."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from PIL import Image, UnidentifiedImageError
from .metadata_parsing import extract_loras
from .metadata_normalization import normalise_lora_name, normalise_text

SUMMARY_FIELDS = (
    ("Model", "model"), ("Seed", "seed"), ("Steps", "steps"),
    ("CFG", "cfg"), ("Sampler", "sampler"),
    ("Scheduler", "scheduler"), ("Denoise", "denoise"),
)

@dataclass(frozen=True, slots=True)
class ParameterComparison:
    name: str
    value_a: str
    value_b: str
    @property
    def differs(self) -> bool:
        return self.value_a != self.value_b

@dataclass(frozen=True, slots=True)
class LoraValue:
    name: str
    model_strength: str = ""
    clip_strength: str = ""

@dataclass(frozen=True, slots=True)
class LoraComparison:
    display_name: str
    value_a: LoraValue | None
    value_b: LoraValue | None
    @property
    def differs(self) -> bool:
        return self.value_a != self.value_b

@dataclass(frozen=True, slots=True)
class MetadataComparison:
    parameters: tuple[ParameterComparison, ...]
    loras: tuple[LoraComparison, ...]

def image_resolution(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as image:
            return image.size
    except (OSError, UnidentifiedImageError):
        return None

def format_resolution(path: Path) -> str:
    size = image_resolution(path)
    return f"{size[0]}×{size[1]}" if size else ""

def compare_parameters(path_a: Path, summary_a: Mapping[str, Any], path_b: Path, summary_b: Mapping[str, Any]) -> tuple[ParameterComparison, ...]:
    rows = [ParameterComparison("Filename", path_a.name, path_b.name)]
    rows.extend(ParameterComparison(label, normalise_text(summary_a.get(key)), normalise_text(summary_b.get(key))) for label, key in SUMMARY_FIELDS)
    rows.append(ParameterComparison("Resolution", format_resolution(path_a), format_resolution(path_b)))
    return tuple(rows)

def _canonical_loras(metadata: Mapping[str, Any]) -> dict[str, LoraValue]:
    result: dict[str, LoraValue] = {}
    for entry in extract_loras(dict(metadata)):
        name = normalise_text(entry.get("name"))
        key = normalise_lora_name(name)
        if key:
            result[key] = LoraValue(name, normalise_text(entry.get("model_strength")), normalise_text(entry.get("clip_strength")))
    return result

def compare_loras(metadata_a: Mapping[str, Any], metadata_b: Mapping[str, Any]) -> tuple[LoraComparison, ...]:
    loras_a, loras_b = _canonical_loras(metadata_a), _canonical_loras(metadata_b)
    rows = []
    for key in sorted(set(loras_a) | set(loras_b)):
        value_a, value_b = loras_a.get(key), loras_b.get(key)
        rows.append(LoraComparison((value_a or value_b).name, value_a, value_b))
    return tuple(rows)

def compare_metadata(path_a: Path, metadata_a: Mapping[str, Any], summary_a: Mapping[str, Any], path_b: Path, metadata_b: Mapping[str, Any], summary_b: Mapping[str, Any]) -> MetadataComparison:
    return MetadataComparison(compare_parameters(path_a, summary_a, path_b, summary_b), compare_loras(metadata_a, metadata_b))
