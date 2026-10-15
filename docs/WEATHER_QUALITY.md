# Weather data-quality validation

T2.4 adds deterministic checks between provider normalization and database insertion.
The raw provider response is always retained, including when a normalized row is
rejected. Quality checks never repair, clamp, or silently invent weather values.

## Record checks and flags

Every hourly record receives one or more stable flags:

| Flag | Meaning | Normalized row stored? |
|---|---|---|
| `valid` | All configured fields are present and within screening limits | Yes |
| `missing` | At least one weather field is null | Yes |
| `interpolated` | Value was filled or interpolated and is not a direct provider value | Yes |
| `out_of_range` | A field is non-numeric, non-finite, or outside its screening range | No |
| `duplicate` | A later row repeats location + UTC hour + source in the same batch | No |
| `outside_window` | Timestamp is outside the requested UTC window | No |

Multiple applicable flags are joined in deterministic order, for example
`missing+interpolated`. Detailed issue codes retain the field name, such as
`missing:pressure_hpa` or `out_of_range:temperature_c`.

Missing and interpolated records remain usable only with their flags. Downstream
forecasting must not present an interpolated value as an observed measurement.

## Screening ranges

These are broad ingestion safety limits, not local climatology and not forecast
thresholds:

| Field | Inclusive range |
|---|---:|
| Temperature | -90 to 65 °C |
| Relative humidity | 0 to 100% |
| Hourly precipitation | 0 to 500 mm |
| Cloud cover | 0 to 100% |
| Wind speed | 0 to 300 km/h |
| Wind direction | 0 to 360° |
| Mean-sea-level pressure | 800 to 1100 hPa |

The limits are centralized in `WEATHER_VALUE_RANGES`. Values outside them are
reported and rejected from the normalized table, while their exact raw payload remains
available for audit and later rule revisions.

## Window report

`WeatherQualityReport` compares received timestamps with the requested half-open UTC
window `[start, end)`. It reports:

- expected, received, unique, accepted, rejected, and fully valid record counts;
- missing-value, out-of-range, duplicate, and interpolated record counts;
- exact missing UTC hours;
- per-field missing and out-of-range counts;
- hourly coverage percentage; and
- an overall `valid`, `warning`, or `invalid` status.

The overall status is `invalid` when a row is rejected, `warning` when hours or values
are missing or interpolated, and `valid` only for complete clean coverage. Coverage is
the percentage of expected timestamps present; it does not conceal invalid field
values.

## Ingestion behavior

The ingestion report includes the complete quality report and `rejected_hours`.
Accepted rows receive their validated flag before idempotent insertion. Re-fetching a
previously stored range is still idempotent and is not treated as a provider duplicate;
duplicate detection applies within the current incoming batch.
