from pathlib import Path

from PIL import Image

from metaview.comparison import compare_loras, compare_parameters, format_resolution
from metaview.metadata_normalization import lora_signature, normalise_prompt


def _lora_metadata(name: str, model: float, clip: float) -> dict:
    return {
        "prompt": {
            "1": {
                "class_type": "LoraLoader",
                "inputs": {
                    "lora_name": name,
                    "strength_model": model,
                    "strength_clip": clip,
                },
            }
        }
    }


def test_prompt_normalisation_ignores_case_and_whitespace() -> None:
    assert normalise_prompt("  A  detailed\nprompt ") == "a detailed prompt"


def test_lora_signature_is_order_independent_and_case_insensitive() -> None:
    first = [
        {"name": "Detail.safetensors", "model_strength": "0.8", "clip_strength": "1"},
        {"name": "Style.safetensors", "model_strength": "0.5", "clip_strength": "0.5"},
    ]
    second = list(reversed([
        {"name": "detail.safetensors", "model_strength": "0.8", "clip_strength": "1"},
        {"name": "STYLE.safetensors", "model_strength": "0.5", "clip_strength": "0.5"},
    ]))
    assert lora_signature(first) == lora_signature(second)


def test_lora_comparison_reports_missing_and_strength_differences() -> None:
    rows = compare_loras(
        _lora_metadata("Detail.safetensors", 0.8, 1.0),
        _lora_metadata("detail.safetensors", 0.6, 1.0),
    )
    assert len(rows) == 1
    assert rows[0].value_a is not None
    assert rows[0].value_b is not None
    assert rows[0].differs
    assert rows[0].value_a.model_strength == "0.8"
    assert rows[0].value_b.model_strength == "0.6"

    missing = compare_loras(_lora_metadata("OnlyA.safetensors", 1, 1), {})
    assert missing[0].value_a is not None
    assert missing[0].value_b is None
    assert missing[0].differs


def test_parameter_comparison_includes_resolution(tmp_path: Path) -> None:
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    Image.new("RGB", (64, 32)).save(a)
    Image.new("RGB", (128, 64)).save(b)
    rows = compare_parameters(a, {"steps": 6}, b, {"steps": 8})
    by_name = {row.name: row for row in rows}
    assert by_name["Steps"].differs
    assert by_name["Resolution"].value_a == "64×32"
    assert by_name["Resolution"].value_b == "128×64"
    assert format_resolution(tmp_path / "missing.png") == ""
