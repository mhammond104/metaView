from metaview.metadata import read_image_metadata


def test_metadata_facade_retains_read_image_metadata_export():
    assert callable(read_image_metadata)


def test_metadata_facade_reads_png_metadata(tmp_path):
    from PIL import Image, PngImagePlugin

    path = tmp_path / "metadata.png"
    pnginfo = PngImagePlugin.PngInfo()
    pnginfo.add_text("prompt", '{"1": {"class_type": "Test", "inputs": {}}}')
    Image.new("RGB", (2, 2)).save(path, pnginfo=pnginfo)

    metadata = read_image_metadata(path)

    assert metadata["prompt"] == {"1": {"class_type": "Test", "inputs": {}}}
