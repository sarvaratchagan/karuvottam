# Hourly Rain-Amount Categories

**Threshold version:** `hourly-rain-categories-1.0`

**Interval:** one completed 60-minute precipitation accumulation `(start, end]`

**Status:** Project-defined experimental categories; not forecast probabilities

## Category boundaries

| Code | Tamil label | Completed-hour precipitation |
|---|---|---:|
| `no_rain` | மழையின்மை | `0.0 ≤ mm < 0.1` |
| `drizzle` | தூறல் / இலேசான மழை | `0.1 ≤ mm < 2.5` |
| `moderate` | மிதமான மழை | `2.5 ≤ mm < 7.5` |
| `heavy` | கனமழை | `mm ≥ 7.5` |

Every lower boundary is inclusive and every finite upper boundary is exclusive. Therefore exactly `0.1`, `2.5`, and `7.5` mm classify as `drizzle`, `moderate`, and `heavy`, respectively.

These are explicit project thresholds selected for reproducible research and boundary testing. They are not represented as an official meteorological warning standard. Changing any boundary requires a new threshold version so stored outputs remain reproducible.

## Interval semantics

The classifier accepts only precipitation accumulated during a declared 60-minute interval. For Open-Meteo ERA5 this is the preceding completed hour whose end is the provider timestamp, as defined in [WEATHER_TIME_SPEC.md](WEATHER_TIME_SPEC.md).

- Missing precipitation returns `unavailable / missing_precipitation`.
- Missing interval metadata returns `unavailable / missing_interval`.
- A declared interval other than 60 minutes returns `unavailable / unsupported_interval`; amounts are not silently rescaled.
- Negative, infinite, NaN, Boolean, or incorrectly typed numeric inputs fail explicitly.
- No missing value is converted to zero.

Daily totals and rolling windows require their own versioned thresholds and must not reuse these hourly boundaries.

## “Drizzle” limitation

True drizzle is a precipitation type normally distinguished using droplet characteristics or a present-weather observation. This project currently has only accumulated rainfall amount. The `drizzle` category is therefore an **amount-based light-rain proxy**, labelled `தூறல் / இலேசான மழை`, and every result carries the caveat `amount_based_light_rain_proxy_not_observed_droplet_classification`.

## Output contract

Each result retains status, category code, Tamil label, amount, interval duration, threshold version, basis, reason code, and caveat. Classification describes an observed accumulation. It does not express likelihood, confidence, or future rain probability.
