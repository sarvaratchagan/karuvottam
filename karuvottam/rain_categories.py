"""Versioned rainfall-amount categories for completed hourly intervals."""

from __future__ import annotations

import math
from dataclasses import dataclass

from karuvottam.data_access import WeatherObservation


THRESHOLD_VERSION = 'hourly-rain-categories-1.0'
SUPPORTED_INTERVAL_MINUTES = 60
CLASSIFICATION_BASIS = 'completed_60_minute_accumulation_mm'
DRIZZLE_CAVEAT = (
    'amount_based_light_rain_proxy_not_observed_droplet_classification'
)


@dataclass(frozen=True)
class RainCategoryDefinition:
    code: str
    label_tamil: str
    minimum_mm: float
    maximum_mm: float | None
    maximum_inclusive: bool = False

    def contains(self, amount_mm: float) -> bool:
        if amount_mm < self.minimum_mm:
            return False
        if self.maximum_mm is None:
            return True
        if self.maximum_inclusive:
            return amount_mm <= self.maximum_mm
        return amount_mm < self.maximum_mm


RAIN_CATEGORIES = (
    RainCategoryDefinition('no_rain', 'மழையின்மை', 0.0, 0.1),
    RainCategoryDefinition('drizzle', 'தூறல் / இலேசான மழை', 0.1, 2.5),
    RainCategoryDefinition('moderate', 'மிதமான மழை', 2.5, 7.5),
    RainCategoryDefinition('heavy', 'கனமழை', 7.5, None),
)


@dataclass(frozen=True)
class RainClassification:
    status: str
    category: str | None
    label_tamil: str
    precipitation_mm: float | None
    interval_minutes: int | None
    threshold_version: str
    classification_basis: str
    reason_code: str | None
    caveat: str

    @property
    def is_available(self) -> bool:
        return self.status == 'classified'


class RainCategoryEngine:
    """Classify observed rainfall amount without probability semantics."""

    def classify(
        self,
        precipitation_mm: float | None,
        interval_minutes: int | None,
    ) -> RainClassification:
        if precipitation_mm is None:
            return self._unavailable(
                precipitation_mm=None,
                interval_minutes=interval_minutes,
                reason_code='missing_precipitation',
            )
        if (
            isinstance(precipitation_mm, bool)
            or not isinstance(precipitation_mm, (int, float))
            or not math.isfinite(float(precipitation_mm))
            or precipitation_mm < 0
        ):
            raise ValueError('precipitation_mm must be a finite non-negative number')
        amount = float(precipitation_mm)

        if interval_minutes is None:
            return self._unavailable(
                precipitation_mm=amount,
                interval_minutes=None,
                reason_code='missing_interval',
            )
        if isinstance(interval_minutes, bool) or not isinstance(interval_minutes, int):
            raise ValueError('interval_minutes must be an integer')
        if interval_minutes <= 0:
            raise ValueError('interval_minutes must be positive')
        if interval_minutes != SUPPORTED_INTERVAL_MINUTES:
            return self._unavailable(
                precipitation_mm=amount,
                interval_minutes=interval_minutes,
                reason_code='unsupported_interval',
            )

        definition = next(
            category for category in RAIN_CATEGORIES if category.contains(amount)
        )
        return RainClassification(
            status='classified',
            category=definition.code,
            label_tamil=definition.label_tamil,
            precipitation_mm=amount,
            interval_minutes=interval_minutes,
            threshold_version=THRESHOLD_VERSION,
            classification_basis=CLASSIFICATION_BASIS,
            reason_code=None,
            caveat=DRIZZLE_CAVEAT,
        )

    def classify_observation(
        self,
        observation: WeatherObservation,
    ) -> RainClassification:
        return self.classify(
            observation.precipitation_mm,
            observation.precipitation_interval_minutes,
        )

    @staticmethod
    def _unavailable(
        *,
        precipitation_mm: float | None,
        interval_minutes: int | None,
        reason_code: str,
    ) -> RainClassification:
        return RainClassification(
            status='unavailable',
            category=None,
            label_tamil='தரவு இல்லை',
            precipitation_mm=precipitation_mm,
            interval_minutes=interval_minutes,
            threshold_version=THRESHOLD_VERSION,
            classification_basis=CLASSIFICATION_BASIS,
            reason_code=reason_code,
            caveat=DRIZZLE_CAVEAT,
        )
