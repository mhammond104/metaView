from pathlib import Path

from PIL import Image

from metaview.experiments import AnalysedImage, analyse_images


def make_image(path: Path, size=(64, 64)) -> Path:
    Image.new("RGB", size).save(path)
    return path


def test_analysis_identifies_fixed_and_variable_fields(tmp_path: Path):
    first = make_image(tmp_path / "a.png")
    second = make_image(tmp_path / "b.png")
    common = {"positive": "portrait", "model": "model.safetensors", "cfg": "1", "sampler": "euler", "scheduler": "beta"}
    images = [
        AnalysedImage(first, {}, {**common, "steps": "6", "seed": "10"}),
        AnalysedImage(second, {}, {**common, "steps": "8", "seed": "10"}),
    ]

    analysis = analyse_images(images)

    assert "Model" in {field.name for field in analysis.fixed}
    assert "Steps" in {field.name for field in analysis.variable}
    assert analysis.warnings == ()


def test_analysis_warns_about_prompt_model_resolution_and_partial_metadata(tmp_path: Path):
    first = make_image(tmp_path / "a.png", (64, 64))
    second = make_image(tmp_path / "b.png", (128, 64))
    images = [
        AnalysedImage(first, {}, {"positive": "one", "model": "a", "steps": "6"}),
        AnalysedImage(second, {}, {"positive": "two", "model": "b", "steps": ""}),
    ]

    analysis = analyse_images(images)

    assert "Positive prompt differs between runs" in analysis.warnings
    assert "Model differs between runs" in analysis.warnings
    assert "Resolution differs between runs" in analysis.warnings
    assert "Steps is missing from one or more runs" in analysis.warnings


def test_analysis_rejects_empty_image_set():
    import pytest
    with pytest.raises(ValueError):
        analyse_images([])
