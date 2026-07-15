from pathlib import Path
from types import SimpleNamespace

from metaview.smart_collections import (
    SmartCollection,
    SmartCollectionRule,
    evaluate_indexed_smart_collection,
)
from datetime import datetime, timezone


def test_smart_collection_matches_user_tags(tmp_path: Path) -> None:
    first = tmp_path / "one.png"
    second = tmp_path / "two.png"
    first.touch()
    second.touch()
    now = datetime.now(timezone.utc)
    collection = SmartCollection(
        1,
        "Portfolio",
        (SmartCollectionRule("tag", "is", "portfolio"),),
        now,
        now,
    )
    images = [
        SimpleNamespace(path=first, model="", sampler="", scheduler="", positive_prompt=""),
        SimpleNamespace(path=second, model="", sampler="", scheduler="", positive_prompt=""),
    ]
    tags = {first.resolve(): ("Portfolio",), second.resolve(): ("Needs Review",)}
    result = evaluate_indexed_smart_collection(
        collection,
        images,
        lambda _path: 0,
        lambda path: tags[path.resolve()],
    )
    assert result == [first.resolve()]
