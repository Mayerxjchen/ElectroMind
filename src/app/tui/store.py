"""ItemStore — 结构化条目 + 每条目独立渲染缓存（替代 LayoutTerminal.body 字符串累积）。

- 每个 RenderItem 的渲染结果按 (color, width 桶) 缓存；条目变化只失效自身。
- 视图文本按需从缓存行拼接；5000 个条目不会触发一次整体重渲染。

宽度桶：resize 只在跨桶时才重排受影响条目。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .render import render_item
from .view_model import RenderItem

_WIDTH_BUCKETS = (40, 60, 80, 100, 120, 160, 200)


def width_bucket(width: int) -> int:
    for bucket in _WIDTH_BUCKETS:
        if width <= bucket:
            return bucket
    return _WIDTH_BUCKETS[-1]


@dataclass(slots=True)
class ItemStore:
    color: bool = True
    items: list[RenderItem] = field(default_factory=list)
    _cache: dict[tuple[str, int, bool], list[str]] = field(default_factory=dict)
    _dirty: set[str] = field(default_factory=set)

    def append(self, item: RenderItem) -> None:
        self.items.append(item)

    def item(self, item_id: str) -> RenderItem | None:
        for entry in self.items:
            if entry.id == item_id:
                return entry
        return None

    def invalidate(self, item_id: str) -> None:
        self._dirty.add(item_id)

    def invalidate_all(self) -> None:
        for item in self.items:
            self._dirty.add(item.id)

    def render_lines(self, width: int) -> list[str]:
        """当前视图行文本（按条目顺序；文本型条目渲染不受宽度影响，直接缓存）。"""
        bucket = width_bucket(width)
        lines: list[str] = []
        for item in self.items:
            key = (item.id, bucket, self.color)
            if key in self._cache and item.id not in self._dirty:
                cached = self._cache[key]
            else:
                cached = render_item(item, color=self.color)
                self._cache[key] = cached
                self._dirty.discard(item.id)
            lines.extend(cached)
            lines.append("")
        return lines
