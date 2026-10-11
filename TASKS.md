# Karuvottam Project Task Backlog

Derived from `PROJECT_PLAN.md` (version 1.1).

## Working conventions

- **Status:** Todo / In Progress / Blocked / Done
- **Owner:** Unassigned until assigned in the project tracker
- **Priority:** P0 = immediate, P1 = core MVP, P2 = usable research release, P3 = production readiness, P4 = future enhancement
- A task is complete only when its implementation, tests, and relevant documentation are complete.
- Forecast output must remain labelled **experimental** until historical validation and calibration support stronger claims.

## Milestones

| Milestone | Scope | Exit condition |
|---|---|---|
| M0 — Stable MVP | Phase 0 | Application starts reliably and smoke tests pass |
| M1 — Core rule engine | Phases 1 and 3 | Calendar, lunar, sunrise, window, and persistence logic pass tests |
| M2 — Data-ready MVP | Phase 2 | Real hourly weather data can be fetched/imported, validated, and stored |
| M3 — Forecast MVP | Phases 4 and 5 | 180/140-day experimental outputs are traceable and visible/exportable |
| M4 — Research validation | Phase 6 | Multi-year backtest and baseline comparison are reproducible |
| M5 — Production release | Phase 7 | Security, recovery, deployment, and monitoring checks pass |
| M6 — Event intelligence | Phase 8 | Historical/current weather events, tracks, climate indices, impacts, and rainfall comparisons are traceable and clearly separated by evidence type |

## Phase 0 — Stabilize the current MVP

| ID | Task | Priority | Depends on | Status | Owner | Done when |
|---|---|---:|---|---|---|---|
| T0.1 | Inventory and run the existing Flask MVP | P0 | — | Done | Unassigned | Current files are inventoried; the app runs locally; key pages open; README startup steps are verified; production debug mode is disabled |
| T0.2 | Establish version-control hygiene | P0 | T0.1 | Done | Unassigned | `.gitignore` excludes `.venv`, `.env`, databases, logs, and temporary exports; the recoverable baseline is committed |
| T0.3 | Add baseline smoke and regression tests | P0 | T0.1 | Done | Unassigned | App import, HTTP 200 home page, core date calculations, and useful error logging are covered by automated tests |

## Phase 1 — Finalize and implement domain rules

| ID | Task | Priority | Depends on | Status | Owner | Done when |
|---|---|---:|---|---|---|---|
| T1.1 | Specify the Aadi 180-day and Margazhi 140-day mappings | P1 | T0.3 | Done | Unassigned | Inclusive/exclusive boundaries, day-1 convention, UTC/local handling, and the exact 248-hour Margazhi duration are documented with examples and tests |
| T1.2 | Implement the modified Tamil calendar engine | P1 | T1.1 | Done | Unassigned | March 21 = Chithirai 1 is configurable/versioned; month/year boundaries and Gregorian↔Tamil conversions pass boundary tests; UI identifies it as a custom rule |
| T1.3 | Implement lunar-event calculation | P1 | T1.1, T3.3 | Done | Unassigned | The first full moon or new moon after the configured Tamil-month start is selected; source, local/UTC timestamps, calculation version, and unavailable-data behavior are stored |
| T1.4 | Implement local sunrise calculation | P1 | T1.3, T3.3 | Done | Unassigned | Sunrise is calculated for the configured location after the four-day settling period and verified in `Asia/Kolkata`; midnight is never substituted |
| T1.5 | Generate Karuvottam observation windows | P1 | T1.2, T1.4 | Done | Unassigned | Aadi uses the preceding Shukla/Krishna Chaturdashi start and lasts 18 full days; Margazhi retains its lunar-event trigger and lasts 248 hours; provenance and rule version are stored and tested |

## Phase 2 — Integrate weather data

| ID | Task | Priority | Depends on | Status | Owner | Done when |
|---|---|---:|---|---|---|---|
| T2.1 | Evaluate and select a historical weather provider | P1 | T1.5 | Done | Unassigned | Hourly precipitation, temperature, humidity, cloud, wind, and optional pressure coverage is confirmed for the target location; limits, licensing, gaps, and timestamp semantics are documented |
| T2.2 | Build the weather-data client | P1 | T2.1, T3.1, T3.3 | Done | Unassigned | Data can be fetched by location/time range; retries handle timeout/rate/API errors; source/raw reference is retained; repeated ingestion is idempotent |
| T2.3 | Normalize timestamps and accumulation periods | P1 | T2.1 | Done | Unassigned | UTC and local timestamps are stored consistently; provider-hour meaning and precipitation accumulation interval are documented and covered by tests |
| T2.4 | Implement data-quality validation | P1 | T2.2, T2.3 | Todo | Unassigned | Range, missingness, duplication, and interpolation checks produce a per-record flag plus a window-level quality report |
| T2.5 | Implement CSV import and export | P2 | T2.4, T3.2 | Todo | Unassigned | Required columns/formats are documented; import supports preview and reports bad rows; UTF-8 Tamil data round-trips; exports are verified |

## Phase 3 — Establish persistence and application structure

| ID | Task | Priority | Depends on | Status | Owner | Done when |
|---|---|---:|---|---|---|---|
| T3.1 | Create the SQLite schema and migrations | P1 | T0.2, T1.1 | Done | Unassigned | All plan tables, keys, timestamp conventions, and migrations exist; weather uniqueness is enforced on location + UTC time + source; data survives restart |
| T3.2 | Create a data-access layer | P1 | T3.1 | Done | Unassigned | SQL is separated from Flask routes; transaction, rollback, and database errors are tested |
| T3.3 | Centralize configuration and secrets | P1 | T0.2 | Done | Unassigned | Location, timezone, calendar reference, and provider settings use config/environment variables; `.env.example` is safe and complete; no secret is committed |

## Phase 4 — Build the experimental forecast engine

| ID | Task | Priority | Depends on | Status | Owner | Done when |
|---|---|---:|---|---|---|---|
| T4.1 | Define and implement deterministic research scoring rules | P2 | T1.5, T2.4 | Todo | Unassigned | Inputs, rationale, thresholds, output, and limitations are documented; identical input gives identical output; the score is not presented as probability |
| T4.2 | Define rain categories | P2 | T4.1 | Todo | Unassigned | No-rain, drizzle, moderate, and heavy thresholds specify amount and interval; boundary-value tests pass |
| T4.3 | Generate 180/140-day experimental forecast timelines | P2 | T1.1, T1.5, T3.2, T4.1, T4.2 | Todo | Unassigned | Target timestamps are correct; every output links to its source window, rule/model version, generation time, and quality; missing inputs produce “no data,” not invented values |
| T4.4 | Calibrate probability output | P3 | T4.3, T6.1, T6.3, T6.4 | Todo | Unassigned | Time-ordered training/evaluation produces documented Brier/reliability results; percentages remain hidden until sufficient calibration evidence exists |

## Phase 5 — Deliver the Tamil web interface

| ID | Task | Priority | Depends on | Status | Owner | Done when |
|---|---|---:|---|---|---|---|
| T5.1 | Build the Tamil status dashboard | P2 | T2.4, T3.2, T4.3 | Todo | Unassigned | Active location, next window, latest data, quality status, latest forecast, and actionable warnings appear on one page |
| T5.2 | Build the Karuvottam calendar view | P2 | T1.5, T3.2 | Todo | Unassigned | Aadi/Margazhi windows, trigger event, four-day settling period, sunrise, start/end, and rule details are visible and traceable |
| T5.3 | Build the rain-forecast calendar | P2 | T4.3, T2.5 | Todo | Unassigned | Day/week/month views show category, available probability, quality, method, experimental/no-data state, and CSV export; layout works on small screens |
| T5.4 | Build the observation-data inspection page | P2 | T2.4, T3.2 | Todo | Unassigned | Time-series views cover required variables; raw/interpolated observations and missing intervals are visually distinct |
| T5.5 | Add UI acceptance and accessibility checks | P2 | T5.1, T5.2, T5.3, T5.4 | Todo | Unassigned | Tamil renders correctly; invalid input and no-data states are understandable; key pages work on desktop/mobile and do not return unexplained 500 errors |

## Phase 6 — Backtest and scientifically evaluate

| ID | Task | Priority | Depends on | Status | Owner | Done when |
|---|---|---:|---|---|---|---|
| T6.1 | Assemble a reproducible multi-year dataset | P2 | T1.5, T2.4, T3.2 | Todo | Unassigned | Historical windows and subsequent observed rainfall are linked; provider, gaps, transformations, and measurement differences are documented |
| T6.2 | Implement baseline comparisons | P2 | T6.1, T4.3 | Todo | Unassigned | Karuvottam-only, seasonal/climatology baseline, and combined-feature approaches run over the same evaluation periods |
| T6.3 | Implement evaluation metrics and reports | P2 | T6.2 | Todo | Unassigned | Appropriate classification, probability, and amount metrics are reported by season, month, and forecast horizon with limitations |
| T6.4 | Implement time-series validation and versioning | P2 | T6.2, T6.3 | Todo | Unassigned | Past years train/configure rules and later years test them; leakage checks pass; dataset, rule, and model versions make results reproducible |
| T6.5 | Publish a research findings summary | P2 | T6.4 | Todo | Unassigned | The summary states whether Karuvottam adds value over baseline, includes uncertainty, and avoids unsupported accuracy claims |

## Phase 7 — Secure, recover, and deploy

| ID | Task | Priority | Depends on | Status | Owner | Done when |
|---|---|---:|---|---|---|---|
| T7.1 | Harden error handling and logging | P3 | M3 | Todo | Unassigned | Users see safe, understandable errors; diagnostic logs omit secrets; API/database recovery behavior is documented and tested |
| T7.2 | Add administration security | P3 | T7.1 | Todo | Unassigned | Admin routes require authentication; inputs are validated; secrets stay in environment variables; debug is off; dependencies are reviewed |
| T7.3 | Implement backup and recovery | P3 | T3.1, T2.5 | Todo | Unassigned | Scheduled database backups and CSV recovery paths exist; a restore test succeeds; the recovery procedure is documented |
| T7.4 | Prepare production deployment | P3 | T7.1, T7.2, T7.3, T6.5 | Todo | Unassigned | WSGI, HTTPS, environment configuration, logs, health monitoring, and the pre-release checklist are verified |
| T7.5 | Add audit history for manual changes and forecast runs | P3 | T3.2, T5.1 | Todo | Unassigned | Actor, action, record, reason, and timestamp are captured for manual edits and prediction-generation history |

## Phase 8 — Integrated weather-event tracking and historical analysis

Establish the historical data model and map before recent/live ingestion. T8.7 applies across the phase and must be completed with each relevant integration.

| ID | Task | Priority | Depends on | Status | Owner | Done when |
|---|---|---:|---|---|---|---|
| T8.1 | Define the common weather-event data model | P2 | T3.1, T3.2 | Todo | Unassigned | UACC, LPA, Depression, Deep Depression, and Cyclone events retain provider classification, stable event keys, complete update history, provenance, quality, and observed/official-forecast/model point types without overwriting intensity changes |
| T8.2 | Build event ingestion, movement tracking, and the track map | P2 | T8.1, T8.7 | Todo | Unassigned | Historical data works first; permitted recent sources then ingest idempotently; tested geometry provides movement/distance; observed, official-forecast, and model-guidance paths remain visually and structurally distinct with source/update details |
| T8.3 | Collect IOD and ENSO climate indices | P3 | T3.1, T8.7 | Todo | Unassigned | DMI/IOD and ENSO/ONI values retain period, issue date, provider, and data version; UI labels them as seasonal context rather than daily local-rain evidence |
| T8.4 | Assess target-location impact | P3 | T2.4, T8.2 | Todo | Unassigned | Distance and motion are combined only with cited rain/model/observation evidence and relevant atmospheric inputs; output exposes data gaps, track/model disagreement, uncertainty, and validation status rather than treating an event as proof of rain |
| T8.5 | Link historical events to rainfall | P2 | T6.1, T8.2 | Todo | Unassigned | Pre/during/post-event rainfall and distance bands are reproducibly compared; historical event/rain inputs preserve provenance and quality; time-ordered train/test evaluation prevents leakage |
| T8.6 | Build the integrated event dashboard | P3 | T8.2, T8.3, T8.4, T8.5, T8.7 | Todo | Unassigned | Map, timeline, latest bulletin, motion, target distance, climate context, and freshness are visible; Karuvottam-only, modern-weather-only, and combined outputs remain separately identifiable and comparable over identical evaluation periods |
| T8.7 | Enforce freshness, provenance, and failure handling | P2 | T2.4, T3.3 | Todo | Unassigned | Every event/index source exposes issue/retrieval time and staleness; unavailable or conflicting data is logged and shown without presenting old data as current |
| T8.8 | Validate any combined Karuvottam/weather model | P3 | T6.4, T8.5, T8.6 | Todo | Unassigned | A combined model is exposed only if leakage-safe historical comparison over the same place, period, and metrics demonstrates incremental value; probabilities remain hidden until calibrated |

## Phase 9 — Future enhancements

| ID | Task | Priority | Depends on | Status | Owner | Done when |
|---|---|---:|---|---|---|---|
| T9.1 | Support multiple locations | P4 | M5 | Todo | Unassigned | Rules, ingestion, windows, predictions, and UI are isolated per location |
| T9.2 | Integrate station/IoT sensor data | P4 | T9.1 | Todo | Unassigned | Sensor observations use a documented schema and participate in provenance and quality checks |
| T9.3 | Add email/message notifications | P4 | M5 | Todo | Unassigned | Users can configure meaningful alerts; delivery failures are visible and retryable |
| T9.4 | Add user accounts and roles | P4 | T7.2 | Todo | Unassigned | Admin, researcher, viewer, and data-maintainer permissions are enforced |
| T9.5 | Package as an installable mobile-friendly web app | P4 | T5.5, M5 | Todo | Unassigned | The supported mobile experience and offline/install behavior are documented and tested |
| T9.6 | Evaluate advanced machine-learning models | P4 | T6.4, T8.8 | Todo | Unassigned | Models use leakage-safe evaluation, calibration, baseline comparison, and versioned reproducible inputs |
| T9.7 | Add Tamil/English language selection | P4 | T5.5 | Todo | Unassigned | All user-facing strings are localizable and both languages pass UI checks |
| T9.8 | Compare multiple weather providers | P4 | T6.1 | Todo | Unassigned | Provider coverage, disagreement, reliability, and impact on evaluation are reported |

## Recommended next implementation sequence

The stabilization, rule-engine, configuration, lunar, sunrise, and observation-window tasks are complete. Continue in this order unless repository inspection reveals a blocker:

1. T3.1 — Create the SQLite schema and migrations, including the new event-analysis tables.
2. T3.2 — Create the data-access layer.
3. T2.1 — Evaluate and select the historical weather provider.
4. T2.2–T2.4 — Fetch, normalize, and quality-check hourly weather data.
5. T2.5 — Add verified CSV import/export.
6. T4.1–T4.3 — Build traceable experimental forecast output.
7. T5.1–T5.5 — Deliver and verify the Tamil interface.
8. T6.1–T6.4 — Assemble and backtest the historical dataset.
9. T8.1–T8.2 — Establish the event model, historical archive, calculations, and track map before recent/live ingestion.
10. T8.3–T8.8 — Add climate context, impact/rainfall analysis, freshness controls, dashboard, and evidence-gated combined-model validation.

## MVP release checklist

- [ ] Application starts on a MacBook using documented steps.
- [ ] Home page and core pages load without errors.
- [ ] Target location and `Asia/Kolkata` are configured.
- [ ] Aadi 18-day and Margazhi 248-hour windows are correct.
- [ ] Recurring 180/140-day mappings pass automated tests.
- [ ] Lunar-event and local-sunrise calculations are verified.
- [ ] Real weather data ingestion or import works.
- [ ] Quality and interpolation are clearly labelled.
- [ ] Predictions and their provenance are stored.
- [ ] CSV export works and preserves Tamil text.
- [ ] Backtest-ready data format exists.
- [ ] Experimental status and scientific limitations are visible in the UI.
