"""Headless analysis of image sets used by experiments."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..comparison import format_resolution
from ..metadata_normalization import normalise_lora_name, normalise_text
from ..metadata_parsing import extract_loras

ANALYSIS_FIELDS = (
    ("Positive prompt", "positive"),
    ("Negative prompt", "negative"),
    ("Model", "model"),
    ("Seed", "seed"),
    ("Steps", "steps"),
    ("CFG", "cfg"),
    ("Sampler", "sampler"),
    ("Scheduler", "scheduler"),
    ("Denoise", "denoise"),
)

@dataclass(frozen=True, slots=True)
class AnalysedImage:
    path: Path
    metadata: Mapping[str, Any]
    summary: Mapping[str, Any]

@dataclass(frozen=True, slots=True)
class FieldAnalysis:
    name: str
    values: tuple[str, ...]

    @property
    def distinct_values(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.values))

    @property
    def is_missing(self) -> bool:
        return any(not value for value in self.values)

    @property
    def is_fixed(self) -> bool:
        values = self.distinct_values
        return len(values) == 1 and bool(values[0])

    @property
    def is_variable(self) -> bool:
        return len(self.distinct_values) > 1

@dataclass(frozen=True, slots=True)
class ExperimentAnalysis:
    fields: tuple[FieldAnalysis, ...]
    warnings: tuple[str, ...]

    @property
    def fixed(self) -> tuple[FieldAnalysis, ...]:
        return tuple(field for field in self.fields if field.is_fixed)

    @property
    def variable(self) -> tuple[FieldAnalysis, ...]:
        return tuple(field for field in self.fields if field.is_variable)

    @property
    def missing(self) -> tuple[FieldAnalysis, ...]:
        return tuple(field for field in self.fields if field.is_missing)


def _lora_signature(metadata: Mapping[str, Any]) -> str:
    entries: list[str] = []
    for lora in extract_loras(dict(metadata)):
        name = normalise_lora_name(normalise_text(lora.get("name")))
        if not name:
            continue
        model = normalise_text(lora.get("model_strength"))
        clip = normalise_text(lora.get("clip_strength"))
        entries.append(f"{name}:{model}:{clip}")
    return "; ".join(sorted(entries))


def analyse_images(images: Sequence[AnalysedImage]) -> ExperimentAnalysis:
    if not images:
        raise ValueError("At least one image is required for analysis")

    fields: list[FieldAnalysis] = []
    for label, key in ANALYSIS_FIELDS:
        fields.append(FieldAnalysis(label, tuple(normalise_text(image.summary.get(key)) for image in images)))
    fields.append(FieldAnalysis("Resolution", tuple(format_resolution(image.path) for image in images)))
    fields.append(FieldAnalysis("LoRAs", tuple(_lora_signature(image.metadata) for image in images)))

    by_name = {field.name: field for field in fields}
    warnings: list[str] = []
    for name in ("Positive prompt", "Negative prompt", "Model", "Resolution"):
        field = by_name[name]
        if field.is_variable:
            warnings.append(f"{name} differs between runs")
    for field in fields:
        if field.is_missing and not all(not value for value in field.values):
            warnings.append(f"{field.name} is missing from one or more runs")
    if all(not normalise_text(image.summary.get("positive")) for image in images):
        warnings.append("No detectable positive prompt metadata")
    return ExperimentAnalysis(tuple(fields), tuple(dict.fromkeys(warnings)))
