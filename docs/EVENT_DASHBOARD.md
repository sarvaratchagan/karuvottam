# T8.6 — Integrated event dashboard

`/events` is the integrated read-only dashboard. It keeps the selected IBTrACS event's South India track map, latest bulletin, movement, target distance, freshness, target-location evidence gaps, and a 12-bulletin timeline together. Observed, official forecast, and model-guidance paths retain separate styles and labels; historical IBTrACS data is never shown as a live warning. The full bulletin table remains below the map.

The [T8.7 source monitor](SOURCE_MONITORING.md) adds a separate poll-health panel for active IBTrACS, DMI and ONI. A successful poll with no usable active rows does not make a historical event current, and a failed poll retains its prior successful retrieval time.

The same page shows the latest stored DMI/IOD and ONI/ENSO periods, values, provider links, issue/retrieval times, quality, and stale status. These are seasonal context **as of their displayed periods**, which may differ from the selected storm's historical period. They are not used to calculate the storm's local impact or the model comparison.

The historical event/rain card reads the T8.5 `summary.json` only after its `event_rainfall.csv` checksum and target coordinates match. The three-way research table reads T6.5 rolling findings only after verifying the findings JSON hash, the rolling metrics hash/key, the source evaluation dataset hash/key and target coordinates, and equal paired-row counts. It uses the **same 2020–2024 rolling evaluation identities** for all three rows:

- modern weather only: prior local ERA5 rainfall seasonal climatology;
- Karuvottam only: the experimental source-window KNN;
- combined: the experimental Karuvottam source-window weather-feature KNN.

This T6 combined candidate does **not** include T8 event tracks or IOD/ENSO indices. The research comparison is displayed as historical error metrics only. It does not publish model rain amounts, probabilities, categories, or an operational combined forecast. In the current evidence, neither Karuvottam candidate demonstrates incremental value over seasonal climatology, and the T8.5 distance-only event model also fails to beat its baseline. The [T8.8 validation](COMBINED_VALIDATION.md) records a withheld decision; any future event/climate-aware candidate needs its own matched validation.

Missing, corrupted, or wrong-location artifacts produce an explicit unavailable state instead of stale or fabricated metrics. Deployment can point to verified artifact directories with `KARUVOTTAM_RESEARCH_FINDINGS_DIR`, `KARUVOTTAM_ROLLING_VALIDATION_DIR`, `KARUVOTTAM_EVALUATION_DATASET_DIR`, `KARUVOTTAM_EVENT_RAINFALL_DIR`, `KARUVOTTAM_SCORE_CALIBRATION_DIR`, and `KARUVOTTAM_COMBINED_VALIDATION_DIR`. Defaults are the matching `data/exports/*-2015-2024` directories under the project root. These generated exports are ignored by Git and must be supplied separately in a deployed environment if the historical cards should appear.
