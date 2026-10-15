# Weather CSV import and export

T2.5 provides a preview-first CSV boundary for normalized hourly weather records.
`WeatherCsvService` parses and validates the entire file before any database write.
The caller explicitly approves the returned preview by passing it to
`import_preview()`.

## Encoding and structure

- Files must be UTF-8; a UTF-8 BOM is accepted but never emitted.
- The first row must be a header.
- Extra named columns are ignored, but every required column below must exist exactly
  once.
- Blank nullable values are represented by an empty field.
- Export uses RFC-style CSV quoting and `\n` line endings in a stable column order.
- Export returns Unicode text. Write it with `encoding='utf-8'` and `newline=''`.

`location_id` is deliberately not read from the CSV. The destination location is an
explicit API argument, preventing a file from redirecting rows to another location.
`observed_at_local` must exactly match that location's stored IANA timezone.

## Required columns

| Column | Format |
|---|---|
| `observed_at_utc` | ISO-8601 exact hour with offset; canonical export ends in `Z` |
| `observed_at_local` | ISO-8601 with numeric offset matching the location timezone |
| `temperature_c` | Number or blank |
| `relative_humidity_pct` | Number or blank |
| `precipitation_mm` | Number or blank |
| `cloud_cover_pct` | Number or blank |
| `wind_speed_kmh` | Number or blank |
| `wind_direction_deg` | Number or blank |
| `pressure_hpa` | Number or blank |
| `source` | Non-empty UTF-8 text |
| `is_interpolated` | `true`, `false`, `1`, or `0` |
| `quality_flag` | Exported audit value; recalculated during import |
| `raw_payload_reference` | UTF-8 text or blank |
| `precipitation_interval_start_utc` | ISO-8601 with offset, or blank with all interval fields |
| `precipitation_interval_end_utc` | ISO-8601 with offset, or blank with all interval fields |
| `precipitation_interval_minutes` | Positive integer, or blank with all interval fields |

Precipitation interval fields are all present or all blank. When present, the end must
equal `observed_at_utc` and the timestamp difference must equal the declared minutes.
Fractional timestamp seconds are rejected.

## Preview and bad rows

```python
csv_service = app.extensions['weather_csv_service']
preview = csv_service.preview_import(csv_bytes, location_id=location_id)

for row in preview.rows:
    print(row.row_number, row.quality_flag, row.errors, row.will_import)

if preview.accepted_rows:
    result = csv_service.import_preview(preview)
```

Syntax, numeric, boolean, timezone, and interval errors receive `invalid_csv` with a
row number and readable error. Successfully parsed rows pass through the same T2.4
quality validator used by API ingestion. Out-of-range and duplicate rows are rejected;
missing and interpolated rows retain explicit flags and may be imported. Internal
missing UTC hours appear in the preview's window quality report.

Import uses the existing identity key `location_id + observed_at_utc + source`.
Re-importing an approved preview reports existing rows and does not create duplicates.
All accepted rows are written in one transaction.

## Export

```python
text = csv_service.export(
    location_id=location_id,
    start_utc=start_utc,
    end_utc=end_utc,
    source='open-meteo:era5',  # optional
)
output_path.write_text(text, encoding='utf-8', newline='')
```

The start and end timestamps are inclusive, matching the repository query. Rows are
ordered by UTC timestamp, source, and database id. Database ids are not exported, so
the file remains portable. UTF-8 Tamil source names and references round-trip without
loss.
