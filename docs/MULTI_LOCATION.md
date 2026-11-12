# T9.1 — Multiple locations

Active locations are selected on the home page. The selected `location` ID is carried through the calendar, observation inspection, event dashboard, forecast view, and CSV link. Each request resolves only an active location; an unknown or inactive ID falls back to the configured default with a notice. The location ID, coordinates, timezone, and optional calendar-rule profile drive that place's calculations.

Weather rows were already keyed by `location_id`. Migration `006_multi_location.sql` adds location-specific calendar rules, rebuilds the stored window identity as `(location_id, season_type, season_year, rule_version)`, and adds `location_id` to forecast runs. Existing window/run rows are assigned to the sole existing location when unambiguous; legacy rows remain unassigned if more than one location already existed. New saved runs require an active location, and the dashboard reads only that location's latest run. The migration checks foreign keys before committing.

Run the migration before using a second location:

```sh
python -m karuvottam.database migrate
```

Add a location and optionally override its calendar rule:

```sh
python -m karuvottam.audit add-location \
  --name 'Example town' --latitude 10.80 --longitude 78.50 \
  --timezone Asia/Kolkata --actor operator --reason 'Add observation site'

python -m karuvottam.audit set-location-rules \
  --location-id 2 --chithirai-reference 03-21 --rule-version 2.0 \
  --margazhi-anchor-year 2026 --margazhi-anchor-phase new_moon \
  --actor operator --reason 'Set local calendar rule'
```

Each new location receives the current configured calendar rule initially. Rule changes affect newly calculated windows and leave saved runs with their original rule version. A different version should be used when the rule meaning changes.

Import historical ERA5 data for the selected place, using dates that cover its Karuvottam window:

```sh
python -m karuvottam.audit ingest-weather \
  --location-id 2 --start-date 2024-07-01 --end-date 2024-07-20 \
  --actor operator --reason 'Import Aadi source-window weather'
```

The command reads that location's stored coordinates and writes only to its observation rows. To save an explicit research forecast run for that location:

```sh
python -m karuvottam.audit generate-forecast \
  --location-id 2 --year 2024 --mode aadi \
  --actor operator --reason 'Historical research run'
```

The previously generated T6/T8 evaluation artifacts are tied to the original project's coordinates. For another location, the event dashboard marks those comparisons unavailable until the historical dataset and validations are rebuilt for that place. No other location's score, saved forecast, or research evidence is substituted.
