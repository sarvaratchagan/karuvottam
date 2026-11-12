# T8.1 — Common weather-event model

The event model accepts five normalized types: `uacc`, `lpa`, `depression`,
`deep_depression`, and `cyclone`. Each provider bulletin is a separate immutable
`weather_events` row. `source + event_key` is the stable identity assigned by the
source; `issued_at` distinguishes updates. No name, position, or time-based fuzzy
matching is performed. T8.2 will ingest selected permitted historical sources and
build movement and map views on this foundation.

## Classification and provenance

`provider_classification` preserves the source's exact label. `event_type` is the
application's normalized category. `classification_basis` says whether that category
follows the provider (`provider_category`) or is an analyst interpretation
(`analyst_interpretation`). An interpretation requires
`classification_rule_version`. Older rows receive `legacy_unspecified` during the
non-destructive migration. These fields do not replace or rewrite the source label.

Each bulletin stores its source, stable event key, source reference and/or URL,
issue time, first retrieval time, quality flag, optional intensity, center position,
central pressure and wind speed. The source reference may be a provider bulletin ID;
URLs are separate. Coordinates must arrive together and pass range/finite checks.
Times are normalized to UTC `Z`. A repeated identical bulletin is a no-op; later
retrieval does not erase the original retrieval time. A conflicting bulletin with
the same source, event key and issue time raises an error rather than overwriting
history. Later issue times preserve strengthening and weakening as new rows.

## Track points

Points belong to a specific bulletin row and carry one of `observed`,
`official_forecast`, or `model_guidance`. Their source, valid time, coordinates and
quality are retained. Forecast and model points require an issue time matching their
parent bulletin; observed points may omit it. Repeated identical points are
idempotent; conflicting points with the same bulletin, type, valid time and source
are rejected. Movement and target-distance fields remain empty at this stage and
will be calculated in T8.2; a forecast path is never stored as an observation.

## Repository example

```python
from karuvottam.event_model import EventAdvisory, EventTrackPoint

with data_access.transaction() as work:
    bulletin, created = work.weather_events.record_advisory(advisory)
    point, point_created = work.weather_events.record_point(bulletin.id, track_point)
    history = work.weather_events.history(advisory.source, advisory.event_key)
```

`EventAdvisory` and `EventTrackPoint` are typed input contracts; the repository
returns immutable records. Bulletin and points can be inserted in one transaction.
No external feed is queried by T8.1. Source licensing, cadence, retrieval failures
and freshness are addressed with T8.2/T8.7.
