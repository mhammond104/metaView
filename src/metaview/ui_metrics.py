"""Shared visual metrics for metaView's compact desktop design system."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UIMetrics:
    radius_small: int = 4
    radius: int = 6
    radius_large: int = 9
    control_padding_v: int = 3
    control_padding_h: int = 7
    menu_padding_v: int = 4
    menu_padding_h: int = 22
    tab_padding_v: int = 5
    tab_padding_h: int = 9
    toolbar_padding_v: int = 3
    toolbar_padding_h: int = 5
    scrollbar_extent: int = 8
    splitter_extent: int = 2
    preview_toolbar_margin_top: int = 10


METRICS = UIMetrics()
