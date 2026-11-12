"""Read-only seasonal context with source and freshness labels."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from karuvottam.data_access import ClimateIndexRecord, DataAccess


@dataclass(frozen=True)
class ClimateContextItem:
    index_type: str
    title: str
    latest: ClimateIndexRecord | None
    recent: tuple[ClimateIndexRecord, ...]
    age_days: int | None
    stale: bool


class ClimateContextService:
    def __init__(self, access: DataAccess) -> None:
        self.access = access

    def build(self, *, today: date | None = None) -> tuple[ClimateContextItem, ...]:
        today = today or datetime.now(timezone.utc).date()
        definitions = (
            ('iod_dmi', 'இந்தியப் பெருங்கடல் இருமுனைச் சுட்டி (DMI)'),
            ('enso_oni', 'ENSO கடல் Niño சுட்டி (ONI)'),
        )
        with self.access.transaction() as work:
            items = []
            for index_type, title in definitions:
                latest = work.climate_indices.latest(index_type)
                recent = work.climate_indices.recent(index_type, limit=12)
                age = max(0, (today - date.fromisoformat(latest.period_end)).days) if latest else None
                items.append(ClimateContextItem(
                    index_type, title, latest, recent, age,
                    age is None or age > 120,
                ))
        return tuple(items)
