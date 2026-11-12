# T8.5 — Historical event and rainfall analysis

Run the database-only analysis after importing NOAA IBTrACS North Indian Ocean tracks and hourly weather data:

```bash
.venv/bin/python -m karuvottam.event_rainfall \
  --start-year 2015 --end-year 2024 \
  --output data/exports/event-rainfall-2015-2024
```

The command writes `event_rainfall.csv` (one row per event) and `summary.json` (distance-band comparison, time-ordered holdout check, and CSV SHA-256). It makes no API requests. Each row carries the event SID, source URL/reference, retrieval time, quality flags, weather source, raw-payload references, observed-track bounds, first and minimum target distance, and the expected/valid hours for each rainfall window. It reads only observed/best-track points, never official forecast or model guidance as observations.

## Measurement contract

The **pre** window is the 24 hours before the first observed position; **during** is from the first to the last observed position; **post** is the 24 hours after the last position. Hour-ending precipitation labels use `(start, end]`. Only source-validated, non-interpolated, 60-minute accumulations whose interval ends at the stored UTC timestamp count. A window with any missing or invalid hour has no rainfall total. Single-position events have no during window and are incomplete. During-window rainfall is normalized to mm per 24 hours to compare events of different durations. This is a retrospective association; overlapping storm windows and seasonal confounding remain possible.

Distance bands are `<250`, `250–499`, `500–999`, and `1000+` km. Descriptive band summaries use the **minimum distance over the full observed path**. The holdout comparison instead uses only the **first observed position's distance band** as its input. Complete events are split by first-observation year: roughly the earliest 70% of years train, later years test. A training event is excluded if its post window reaches the test cutoff. The test outcome is during-event local rain intensity. The simple band-mean model falls back to the training-wide mean when its band has no training examples; the baseline always uses that training-wide mean. Both are scored with mean absolute error on the same test events. At least five training and two test events are required.

This holdout is a research check, **not operational forecast validation**: IBTrACS historical best tracks may be revised after an event, and ERA5 is gridded reanalysis rather than a local rain gauge. It does not establish event causality, a calibrated rain probability, or target-area impact. `T8.8` must separately validate any combined model before display.

## Current 2015–2024 local run

The bundled database run produced 113 historical events, 109 with complete pre/during/post rainfall windows. The 2022–2024 holdout contained 38 events after 71 training events from earlier years. Baseline MAE was **3.17 mm/24h**; first-position distance-band MAE was **3.22 mm/24h**. Thus this distance-only model did not improve on the training-mean baseline. The closest-path band had only three complete events and **zero** training examples based on first-position distance; its descriptive mean is too sparse to support a forecast claim. The exact output, inputs, and checksum are in the generated artifacts under `data/exports/event-rainfall-2015-2024/`.
