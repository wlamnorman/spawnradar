"""TagProfile and WeightedTag — structured containers for a game's tag set."""

from __future__ import annotations

from dataclasses import dataclass

from app.games.tags._types import TagWeight


@dataclass(frozen=True)
class WeightedTag:
    """A tag paired with a relative importance score for ranking and queries."""

    name: str
    weight: float
    label: TagWeight


@dataclass(frozen=True)
class TagProfile:
    """A tag set split into primary and secondary buckets.

    Tags in *primary* are the strongest signal (weight 1.0). Tags in
    *secondary* carry moderate weight (0.72).

    Only the genre dimension uses both buckets. Mechanics, vibe and kindred
    profiles only populate *primary* — any tag (including ones not in the
    catalog) can appear there.

    Profiles are immutable. Use ``build_tag_profile`` in ``_api`` to
    construct them from raw form input.
    """

    primary: tuple[str, ...] = ()
    secondary: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.primary or self.secondary)

    def __len__(self) -> int:
        return len(self.primary) + len(self.secondary)

    @classmethod
    def empty(cls) -> TagProfile:
        """Return a profile with no tags."""
        return cls()

    @classmethod
    def from_flat_tags(
        cls,
        tags: list[str],
        *,
        default_weight: TagWeight = TagWeight.PRIMARY,
    ) -> TagProfile:
        """Build a single-bucket profile from a flat list of tags."""
        cleaned = tuple(_dedupe(tags))
        if default_weight is TagWeight.PRIMARY:
            return cls(primary=cleaned)
        return cls(secondary=cleaned)

    @classmethod
    def from_json_value(cls, value: object) -> TagProfile:
        """Deserialise from a JSON dict (as stored in the database).

        Legacy ``custom`` entries are promoted to ``primary`` for backward
        compatibility with profiles written before the custom bucket was removed.
        """
        if not isinstance(value, dict):
            return cls.empty()
        primary = [t for t in value.get("primary", []) if isinstance(t, str)]
        secondary = [
            t for t in value.get("secondary", []) if isinstance(t, str)
        ]
        legacy_custom = [
            t for t in value.get("custom", []) if isinstance(t, str)
        ]
        primary = _dedupe(
            primary + [t for t in legacy_custom if t not in primary]
        )
        return cls(
            primary=tuple(primary),
            secondary=tuple(secondary),
        )

    def to_json_value(self) -> dict[str, list[str]]:
        """Serialise to a JSON-compatible dict."""
        return {
            "primary": list(self.primary),
            "secondary": list(self.secondary),
        }

    @property
    def all_tags(self) -> list[str]:
        """All tags in priority order, deduplicated."""
        return _dedupe([*self.primary, *self.secondary])

    def ordered_tags(self) -> list[str]:
        """Alias for ``all_tags`` — kept for backward compatibility."""
        return self.all_tags

    def weighted_tags(self) -> list[WeightedTag]:
        """Return tags annotated with their numeric weight and label."""
        result: list[WeightedTag] = []
        for tag in self.primary:
            result.append(
                WeightedTag(name=tag, weight=1.0, label=TagWeight.PRIMARY)
            )
        for tag in self.secondary:
            result.append(
                WeightedTag(name=tag, weight=0.72, label=TagWeight.SECONDARY)
            )
        return result

    def merge(self, other: TagProfile) -> TagProfile:
        """Return a new profile combining *self* and *other*.

        When the same tag appears in both, the higher-weight bucket wins.
        Within each bucket, *self*'s tags come first.
        """
        from app.games.tags._api import _merge_weighted_buckets

        combined: dict[TagWeight, list[str]] = {
            TagWeight.PRIMARY: list(self.primary) + list(other.primary),
            TagWeight.SECONDARY: list(self.secondary) + list(other.secondary),
        }
        merged = _merge_weighted_buckets(combined)
        return TagProfile(
            primary=tuple(merged[TagWeight.PRIMARY]),
            secondary=tuple(merged[TagWeight.SECONDARY]),
        )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            result.append(v)
    return result
