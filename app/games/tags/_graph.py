"""Tag similarity graph.

Loads tag_graph.json once at import time and exposes a fast lookup of
related tags (neighbours) by name.  Used by the scoring engine to give
partial credit when a prospect mentions a tag that is semantically adjacent
to one of the game's tags.
"""
from __future__ import annotations

import json
from pathlib import Path

_GRAPH_PATH = Path(__file__).parent.parent / "tag_graph.json"


class TagGraph:
    def __init__(self, path: Path = _GRAPH_PATH) -> None:
        # Bidirectional adjacency: tag_name -> list[(neighbour_name, weight)]
        self._adj: dict[str, list[tuple[str, float]]] = {}
        edges = json.loads(path.read_text())
        for e in edges:
            src = e.get("from", "")
            dst = e.get("to", "")
            if not src or not dst:
                continue
            w = float(e.get("weight", 0.0))
            self._adj.setdefault(src, []).append((dst, w))
            self._adj.setdefault(dst, []).append((src, w))

    def related_tags(self, tag: str, min_weight: float = 0.60) -> list[tuple[str, float]]:
        """Return (neighbour, weight) pairs for *tag*, filtered by min_weight.

        Results preserve source order (descending weight) so the first
        match found is always the strongest one.
        """
        return [(n, w) for n, w in self._adj.get(tag.lower(), []) if w >= min_weight]


tag_graph = TagGraph()
