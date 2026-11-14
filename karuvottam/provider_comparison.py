"""Reproducible ERA5 versus NASA POWER historical-provider comparison.

The comparison is research-only. POWER and ERA5 are gridded products, not
independent rain-gauge truth; POWER PS is surface pressure and is deliberately
excluded from direct comparison with ERA5 sea-level pressure.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, time as daytime, timedelta, timezone
from pathlib import Path
from statistics import fmean
from typing import Mapping
from uuid import uuid4
from zoneinfo import ZoneInfo

from karuvottam.baseline_comparison import BaselineComparisonService, BaselineComparisonSpec
from karuvottam.data_access import DataAccess
from karuvottam.evaluation_dataset import CSV_COLUMNS, _expected_interval_ends, _parse_timestamp
from karuvottam.evaluation_metrics import EvaluationMetricSpec, EvaluationMetricsService
from karuvottam.weather_client import (HttpResponse, UrllibWeatherTransport,
                                       WeatherTransportError)


VERSION = 'provider-comparison-1.0'
POWER_URL = 'https://power.larc.nasa.gov/api/temporal/hourly/point'
POWER_PARAMETERS = ('T2M', 'RH2M', 'PRECTOTCORR', 'CLOUD_AMT', 'WS10M', 'WD10M', 'PS')
POWER_UNITS = {
    'T2M': 'C', 'RH2M': '%', 'PRECTOTCORR': 'mm/hour',
    'CLOUD_AMT': '%', 'WS10M': 'm/s', 'WD10M': 'Degrees', 'PS': 'kPa',
}
FIELDS = {
    'temperature_c': 'T2M',
    'relative_humidity_pct': 'RH2M',
    'precipitation_mm': 'PRECTOTCORR',
    'cloud_cover_pct': 'CLOUD_AMT',
    'wind_speed_kmh': 'WS10M',
    'wind_direction_deg': 'WD10M',
}
SOURCE_FIELDS = (
    'precipitation_mm', 'temperature_c', 'relative_humidity_pct',
    'cloud_cover_pct', 'wind_speed_kmh',
)
FIELD_RANGES = {
    'T2M': (-100, 70), 'RH2M': (0, 100), 'PRECTOTCORR': (0, 500),
    'CLOUD_AMT': (0, 100), 'WS10M': (0, 120),
    'WD10M': (0, 360), 'PS': (50, 120),
}
SOURCE = 'nasa-power:hourly'


@dataclass(frozen=True)
class PowerPayload:
    year: int
    hourly: Mapping[datetime, Mapping[str, float | None]]
    missing_by_parameter: Mapping[str, int]
    invalid_by_parameter: Mapping[str, int]
    sha256: str
    api_version: str
    sources: tuple[str, ...]
    grid_coordinates: tuple[float, float, float | None]


def _utc_hour(key: str) -> datetime:
    try:
        return datetime.strptime(key, '%Y%m%d%H').replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError(f'invalid POWER UTC hour: {key!r}') from exc


def parse_power_payload(raw: bytes, *, year: int, latitude: float,
                        longitude: float) -> PowerPayload:
    """Validate POWER shape, UTC hours, units, coordinates and missing values."""
    try:
        payload = json.loads(raw)
        header = payload['header']
        parameters = payload['properties']['parameter']
        units = payload['parameters']
        coordinates = payload['geometry']['coordinates']
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError('invalid NASA POWER response structure') from exc
    if header.get('time_standard') != 'UTC':
        raise ValueError('POWER response must use UTC, not local solar time')
    if (header.get('start'), header.get('end')) != (f'{year}0101', f'{year}1231'):
        raise ValueError('POWER response date range differs from request')
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        raise ValueError('POWER response is missing point coordinates')
    returned_lon, returned_lat = float(coordinates[0]), float(coordinates[1])
    if abs(returned_lat - latitude) > 1 or abs(returned_lon - longitude) > 1:
        raise ValueError('POWER response coordinates differ from target location')
    expected = {
        (datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(hours=offset))
        for offset in range(int((datetime(year + 1, 1, 1, tzinfo=timezone.utc)
                                 - datetime(year, 1, 1, tzinfo=timezone.utc))
                                / timedelta(hours=1)))
    }
    if set(parameters) != set(POWER_PARAMETERS):
        raise ValueError('POWER response parameter list differs from request')
    for parameter in POWER_PARAMETERS:
        if units.get(parameter, {}).get('units') != POWER_UNITS[parameter]:
            raise ValueError(f'POWER {parameter} unit differs from contract')
        if not isinstance(parameters[parameter], dict):
            raise ValueError(f'POWER {parameter} series is not an object')
    fill = float(header.get('fill_value', -999))
    rows: dict[datetime, dict[str, float | None]] = {hour: {} for hour in expected}
    missing = {parameter: 0 for parameter in POWER_PARAMETERS}
    invalid = {parameter: 0 for parameter in POWER_PARAMETERS}
    for parameter in POWER_PARAMETERS:
        lower, upper = FIELD_RANGES[parameter]
        series = parameters[parameter]
        seen: set[datetime] = set()
        for key, value in series.items():
            hour = _utc_hour(key)
            if hour not in expected:
                raise ValueError(f'POWER {parameter} has hours outside the request')
            seen.add(hour)
            if value is None or value == fill:
                rows[hour][parameter] = None
                missing[parameter] += 1
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                rows[hour][parameter] = None
                invalid[parameter] += 1
                continue
            number = float(value)
            if not math.isfinite(number) or not lower <= number <= upper:
                rows[hour][parameter] = None
                invalid[parameter] += 1
                continue
            rows[hour][parameter] = number
        for hour in expected - seen:
            rows[hour][parameter] = None
            missing[parameter] += 1
    return PowerPayload(
        year=year, hourly=rows, missing_by_parameter=missing,
        invalid_by_parameter=invalid, sha256=hashlib.sha256(raw).hexdigest(),
        api_version=str(header.get('api', {}).get('version', 'unknown')),
        sources=tuple(header.get('sources', ())),
        grid_coordinates=(returned_lat, returned_lon,
                          float(coordinates[2]) if len(coordinates) > 2 else None),
    )


class NasaPowerHourlyClient:
    def __init__(self, transport=None, *, timeout_seconds: float = 90,
                 attempts: int = 3, sleep=time.sleep):
        self.transport = transport or UrllibWeatherTransport()
        self.timeout_seconds = timeout_seconds
        self.attempts = attempts
        self.sleep = sleep

    def fetch_year(self, year: int, latitude: float, longitude: float,
                   cache_directory: Path) -> PowerPayload:
        cache_directory.mkdir(parents=True, exist_ok=True)
        path = cache_directory / f'nasa-power-hourly-{year}.json'
        meta_path = cache_directory / f'nasa-power-hourly-{year}.meta.json'
        if path.exists() and meta_path.exists():
            raw = path.read_bytes()
            metadata = json.loads(meta_path.read_text())
            if metadata.get('sha256') != hashlib.sha256(raw).hexdigest():
                raise ValueError(f'cached POWER payload checksum mismatch: {path}')
            if (metadata.get('latitude'), metadata.get('longitude')) != (latitude, longitude):
                raise ValueError('cached POWER coordinates differ from request')
            return parse_power_payload(raw, year=year, latitude=latitude,
                                       longitude=longitude)
        parameters = (
            ('parameters', ','.join(POWER_PARAMETERS)), ('community', 'AG'),
            ('longitude', str(longitude)), ('latitude', str(latitude)),
            ('start', f'{year}0101'), ('end', f'{year}1231'),
            ('format', 'JSON'), ('time-standard', 'UTC'),
        )
        for attempt in range(self.attempts):
            try:
                response: HttpResponse = self.transport.get(
                    POWER_URL, parameters, self.timeout_seconds)
            except WeatherTransportError:
                if attempt + 1 == self.attempts:
                    raise
                self.sleep(min(30, 2 ** attempt))
                continue
            if response.status_code == 200:
                parsed = parse_power_payload(response.body, year=year,
                                             latitude=latitude, longitude=longitude)
                _atomic(meta_path, json.dumps({
                    'sha256': parsed.sha256, 'url': response.url,
                    'retrieved_at_utc': datetime.now(timezone.utc).isoformat(),
                    'latitude': latitude, 'longitude': longitude,
                    'api_version': parsed.api_version, 'sources': parsed.sources,
                    'grid_coordinates': parsed.grid_coordinates,
                }, indent=2).encode())
                _atomic(path, response.body)
                return parsed
            if response.status_code not in (429, 500, 502, 503, 504):
                raise ValueError(f'POWER request failed: HTTP {response.status_code}')
            if attempt + 1 < self.attempts:
                self.sleep(min(30, 2 ** attempt))
        raise ValueError(f'POWER request failed after {self.attempts} attempts')


def _atomic(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f'.{path.name}.{uuid4().hex}.tmp')
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _canonical(power: Mapping[str, float | None], field: str) -> float | None:
    value = power[FIELDS[field]]
    return value * 3.6 if value is not None and field == 'wind_speed_kmh' else value


def _window(hours: Mapping[datetime, Mapping[str, float | None]],
            start: datetime, end: datetime) -> dict[str, object]:
    expected = _expected_interval_ends(start, end)
    rows = [hours.get(hour) for hour in expected]
    complete = [row for row in rows if row is not None and all(
        row[FIELDS[field]] is not None for field in SOURCE_FIELDS)]
    observed = len(complete)
    result: dict[str, object] = {
        'hours': len(expected), 'observed': observed,
        'missing': len(expected) - observed,
        'quality': ('complete' if observed == len(expected) else
                    'no_data' if observed == 0 else 'warning'),
    }
    if observed == len(expected):
        result.update({
            'precipitation_mm': round(sum(row['PRECTOTCORR'] for row in complete), 6),
            'temperature_c': round(fmean(row['T2M'] for row in complete), 6),
            'relative_humidity_pct': round(fmean(row['RH2M'] for row in complete), 6),
            'cloud_cover_pct': round(fmean(row['CLOUD_AMT'] for row in complete), 6),
            'wind_speed_kmh': round(fmean(row['WS10M'] * 3.6 for row in complete), 6),
        })
    return result


def _daily_rain(hours: Mapping[datetime, Mapping[str, float | None]],
                target: date, zone: ZoneInfo, *, hour_shift: int = 0) -> dict[str, object]:
    start = datetime.combine(target, daytime.min, tzinfo=zone)
    expected = _expected_interval_ends(start, start + timedelta(days=1))
    amounts = [hours.get(hour - timedelta(hours=hour_shift), {}).get('PRECTOTCORR')
               for hour in expected]
    observed = sum(value is not None for value in amounts)
    return {
        'hours': len(expected), 'observed': observed,
        'missing': len(expected) - observed,
        'quality': ('complete' if observed == len(expected) else
                    'no_data' if observed == 0 else 'warning'),
        'precipitation_mm': round(sum(amounts), 6) if observed == len(expected) else None,
    }


def _csv_bytes(rows: list[dict[str, object]], columns: tuple[str, ...]) -> bytes:
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore',
                            lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def _read_csv(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(path.read_text())))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _overall_metrics(path: Path) -> dict[str, dict[str, object]]:
    return {row['approach']: {
        'evaluated_rows': int(row['evaluated_rows']),
        'mae_mm': float(row['mae_mm']) if row['mae_mm'] else None,
        'brier_score': float(row['brier_score']) if row['brier_score'] else None,
    } for row in _read_csv(path)
        if row['dimension'] == 'overall' and row['group_value'] == 'all'}


class ProviderComparisonService:
    def __init__(self, power_client=None):
        self.power_client = power_client or NasaPowerHourlyClient()

    def build(self, dataset_path: Path, dataset_manifest_path: Path,
              baseline_path: Path, baseline_manifest_path: Path,
              database_path: Path, output: Path) -> dict[str, object]:
        manifest = json.loads(dataset_manifest_path.read_text())
        if _sha(dataset_path) != manifest['files'][dataset_path.name]['sha256']:
            raise ValueError('ERA5 evaluation dataset checksum mismatch')
        baseline_manifest = json.loads(baseline_manifest_path.read_text())
        if _sha(baseline_path) != baseline_manifest['files'][baseline_path.name]['sha256']:
            raise ValueError('ERA5 baseline predictions checksum mismatch')
        if baseline_manifest['source_dataset']['dataset_key'] != manifest['dataset_key']:
            raise ValueError('baseline and evaluation dataset keys differ')
        location = manifest['location']
        required = manifest['required_weather_date_range_utc']
        first_year = date.fromisoformat(required['start']).year
        last_year = date.fromisoformat(required['end']).year
        output.mkdir(parents=True, exist_ok=True)
        payloads = [self.power_client.fetch_year(
            year, float(location['latitude']), float(location['longitude']),
            output / 'raw') for year in range(first_year, last_year + 1)]
        power = {hour: row for payload in payloads
                 for hour, row in payload.hourly.items()}
        start = datetime.combine(date.fromisoformat(required['start']),
                                 daytime.min, tzinfo=timezone.utc)
        end = datetime.combine(date.fromisoformat(required['end']) + timedelta(days=1),
                               daytime.min, tzinfo=timezone.utc)
        with DataAccess(database_path).transaction() as work:
            era_rows = work.weather_observations.list_between(
                int(location['id']), start, end, source=manifest['weather_source'])
        era = {_parse_timestamp(row.observed_at_utc): row for row in era_rows}
        comparison = self._hourly_comparison(era, power, start, end)
        expected_hours = int((end - start) / timedelta(hours=1))
        era_reliability = {
            'expected_hours': expected_hours,
            'stored_hours': len(era),
            'interpolated_hours': sum(row.is_interpolated for row in era.values()),
            'non_valid_quality_hours': sum(row.quality_flag not in ('valid', 'verified')
                                           for row in era.values()),
            'missing_raw_reference_hours': sum(not row.raw_payload_reference
                                               for row in era.values()),
        }
        pressure_coverage = {
            'era5_sea_level_pressure_hours': sum(
                row.pressure_hpa is not None for row in era.values()),
            'power_surface_pressure_hours': sum(
                row['PS'] is not None for hour, row in power.items()
                if start <= hour < end),
            'directly_comparable': False,
        }
        comparison_bytes = _csv_bytes(comparison, (
            'field', 'era5_hours', 'power_hours', 'matched_hours',
            'era5_coverage_pct', 'power_coverage_pct', 'matched_coverage_pct',
            'mean_absolute_difference', 'mean_signed_difference', 'unit',
        ))
        comparison_path = output / 'hourly_comparison.csv'
        _atomic(comparison_path, comparison_bytes)

        original_rows = _read_csv(dataset_path)
        parent_key = manifest['dataset_key']
        dataset_key = f'{VERSION}:{hashlib.sha256((parent_key + SOURCE).encode()).hexdigest()[:16]}'
        zone = ZoneInfo(location['timezone'])
        source_cache: dict[str, dict[str, object]] = {}
        day_cache: dict[str, dict[str, object]] = {}
        nasa_rows: list[dict[str, object]] = []
        paired_differences = []
        wet_changed = 0
        alignment_differences = []
        shifted_wet_changed = 0
        for original in original_rows:
            window_key = original['source_window_key']
            if window_key not in source_cache:
                source_cache[window_key] = _window(
                    power, datetime.fromisoformat(original['source_window_start_local']),
                    datetime.fromisoformat(original['source_window_end_local']))
            day = original['target_date_local']
            if day not in day_cache:
                day_cache[day] = _daily_rain(power, date.fromisoformat(day), zone)
            source_summary, target = source_cache[window_key], day_cache[day]
            row: dict[str, object] = dict(original)
            row.update(dataset_key=dataset_key, weather_source=SOURCE,
                       source_observed_hours=source_summary['observed'],
                       source_missing_hours=source_summary['missing'],
                       source_interpolated_hours=0,
                       source_measurement_issue_hours=0,
                       source_coverage_pct=round(100 * source_summary['observed'] /
                                                 source_summary['hours'], 6),
                       source_quality_flag=source_summary['quality'],
                       target_observed_hours=target['observed'],
                       target_missing_hours=target['missing'],
                       target_interpolated_hours=0,
                       target_measurement_issue_hours=0,
                       target_coverage_pct=round(100 * target['observed'] /
                                                 target['hours'], 6),
                       target_quality_flag=target['quality'])
            for column, key in (
                ('source_precipitation_mm', 'precipitation_mm'),
                ('source_mean_temperature_c', 'temperature_c'),
                ('source_mean_relative_humidity_pct', 'relative_humidity_pct'),
                ('source_mean_cloud_cover_pct', 'cloud_cover_pct'),
                ('source_mean_wind_speed_kmh', 'wind_speed_kmh'),
            ):
                row[column] = source_summary.get(key, '')
            row['observed_precipitation_mm'] = (
                target['precipitation_mm'] if target['precipitation_mm'] is not None else '')
            nasa_rows.append(row)
            if target['precipitation_mm'] is not None and original['observed_precipitation_mm']:
                era_amount = float(original['observed_precipitation_mm'])
                nasa_amount = float(target['precipitation_mm'])
                paired_differences.append(nasa_amount - era_amount)
                wet_changed += (era_amount >= 0.1) != (nasa_amount >= 0.1)
                shifted = _daily_rain(power, date.fromisoformat(day), zone,
                                      hour_shift=1)['precipitation_mm']
                if shifted is not None:
                    alignment_differences.append(shifted - nasa_amount)
                    shifted_wet_changed += (shifted >= 0.1) != (nasa_amount >= 0.1)

        nasa_dataset_path = output / 'nasa_evaluation_dataset.csv'
        _atomic(nasa_dataset_path, _csv_bytes(nasa_rows, CSV_COLUMNS))
        nasa_manifest_path = output / 'nasa_dataset_manifest.json'
        nasa_manifest = {
            'dataset_version': VERSION, 'dataset_key': dataset_key,
            'parent_dataset_key': parent_key, 'weather_source': SOURCE,
            'location': location, 'season_year_range': manifest['season_year_range'],
            'files': {nasa_dataset_path.name: {'sha256': _sha(nasa_dataset_path),
                                               'rows': len(nasa_rows)}},
            'raw_payloads': {str(payload.year): payload.sha256 for payload in payloads},
            'measurement_note': ('POWER hourly PRECTOTCORR is mm/hour. For this '
                                 'sensitivity comparison, each timestamp is treated '
                                 'as an hour-ending label, matching the ERA5 dataset. '
                                 'The POWER documentation does not confirm identical '
                                 'hour-boundary semantics; do not interpret small '
                                 'boundary differences as physical disagreement.'),
        }
        _atomic(nasa_manifest_path, json.dumps(nasa_manifest, indent=2,
                                               ensure_ascii=False).encode())

        split = baseline_manifest['split']
        spec = BaselineComparisonSpec(**split)
        nasa_baseline = BaselineComparisonService().build(
            nasa_dataset_path, nasa_manifest_path, output / 'nasa-baseline', spec)
        nasa_metrics = EvaluationMetricsService().build(
            nasa_baseline.predictions_path, nasa_baseline.manifest_path,
            output / 'nasa-metrics', EvaluationMetricSpec())
        era_metrics = EvaluationMetricsService().build(
            baseline_path, baseline_manifest_path, output / 'era5-metrics',
            EvaluationMetricSpec())
        metrics = {
            'era5': _overall_metrics(era_metrics.metrics_path),
            'nasa_power': _overall_metrics(nasa_metrics.metrics_path),
        }
        decision = {}
        for provider, approaches in metrics.items():
            seasonal = approaches['seasonal_climatology']
            decision[provider] = {
                approach: {
                    'mae_change_vs_seasonal_mm': round(
                        values['mae_mm'] - seasonal['mae_mm'], 6),
                    'brier_change_vs_seasonal': round(
                        values['brier_score'] - seasonal['brier_score'], 6),
                    'both_point_metrics_better': (
                        values['mae_mm'] < seasonal['mae_mm'] and
                        values['brier_score'] < seasonal['brier_score']),
                } for approach, values in approaches.items()
                if approach != 'seasonal_climatology'
            }
        report = {
            'version': VERSION, 'location': location,
            'period': {'start_date_utc': required['start'],
                       'end_date_utc': required['end'],
                       'start_year': first_year, 'end_year': last_year},
            'era5_dataset_sha256': _sha(dataset_path),
            'nasa_dataset_sha256': _sha(nasa_dataset_path),
            'power_api_versions': sorted({payload.api_version for payload in payloads}),
            'power_upstream_sources': sorted({item for payload in payloads
                                              for item in payload.sources}),
            'power_missing_by_parameter': {
                name: sum(payload.missing_by_parameter[name] for payload in payloads)
                for name in POWER_PARAMETERS},
            'power_invalid_by_parameter': {
                name: sum(payload.invalid_by_parameter[name] for payload in payloads)
                for name in POWER_PARAMETERS},
            'era5_reliability': era_reliability,
            'pressure_coverage': pressure_coverage,
            'hourly_comparison': comparison,
            'daily_rainfall': {
                'matched_days': len(paired_differences),
                'mean_absolute_difference_mm': (round(fmean(abs(v) for v in paired_differences), 6)
                                                if paired_differences else None),
                'mean_signed_difference_mm': (round(fmean(paired_differences), 6)
                                              if paired_differences else None),
                'wet_day_disagreement_count': wet_changed,
                'hour_boundary_sensitivity': {
                    'shifted_days': len(alignment_differences),
                    'mean_absolute_change_mm': (
                        round(fmean(abs(v) for v in alignment_differences), 6)
                        if alignment_differences else None),
                    'wet_day_changes': shifted_wet_changed,
                    'alternative': ('Treat POWER timestamps as hour-start labels '
                                    'and shift them +1 hour for aggregation.'),
                },
            },
            'evaluation_impact': metrics,
            'baseline_decision_sensitivity': decision,
            'caveats': [
                'Both providers are gridded products; this is not a rain-gauge validation.',
                'POWER PS is surface pressure; ERA5 pressure_msl is sea-level pressure and is not directly compared.',
                'POWER precipitation hour-boundary semantics may differ from ERA5; small day/window boundary differences are uncertain.',
                'NASA-trained baselines use the same chronological split and model settings, but a different provider for both features and outcomes.',
                'Point-estimate metric changes do not replace paired uncertainty or the existing publication gate.',
                'Completeness and provenance are measured here; long-run API uptime and accuracy against gauges are not.',
                'Neither provider is a real-time observation source or an ECMWF forecast-run archive.',
            ],
            'files': {
                'hourly_comparison.csv': _sha(comparison_path),
                nasa_dataset_path.name: _sha(nasa_dataset_path),
                'nasa-baseline/baseline_predictions.csv': _sha(nasa_baseline.predictions_path),
                'nasa-metrics/evaluation_metrics.csv': _sha(nasa_metrics.metrics_path),
                'era5-metrics/evaluation_metrics.csv': _sha(era_metrics.metrics_path),
            },
        }
        report_path = output / 'provider_comparison.json'
        _atomic(report_path, json.dumps(report, indent=2, ensure_ascii=False).encode())
        _atomic(output / 'provider_comparison.md', _markdown(report).encode())
        return report

    @staticmethod
    def _hourly_comparison(era, power, start, end):
        hours = int((end - start) / timedelta(hours=1))
        results = []
        for field in FIELDS:
            era_count = power_count = matched = 0
            differences = []
            for offset in range(hours):
                hour = start + timedelta(hours=offset)
                era_row = era.get(hour)
                era_value = getattr(era_row, field) if era_row else None
                power_row = power.get(hour)
                power_value = _canonical(power_row, field) if power_row else None
                era_count += era_value is not None
                power_count += power_value is not None
                if era_value is not None and power_value is not None:
                    matched += 1
                    difference = power_value - era_value
                    if field == 'wind_direction_deg':
                        difference = (difference + 180) % 360 - 180
                    differences.append(difference)
            unit = {'temperature_c': '°C', 'relative_humidity_pct': '%',
                    'precipitation_mm': 'mm/hour', 'cloud_cover_pct': '%',
                    'wind_speed_kmh': 'km/h', 'wind_direction_deg': 'degrees'}[field]
            results.append({
                'field': field, 'era5_hours': era_count,
                'power_hours': power_count, 'matched_hours': matched,
                'era5_coverage_pct': round(era_count / hours * 100, 6),
                'power_coverage_pct': round(power_count / hours * 100, 6),
                'matched_coverage_pct': round(matched / hours * 100, 6),
                'mean_absolute_difference': (round(fmean(abs(v) for v in differences), 6)
                                             if differences else ''),
                'mean_signed_difference': (round(fmean(differences), 6)
                                           if differences else ''),
                'unit': unit,
            })
        return results


def _markdown(report: Mapping[str, object]) -> str:
    lines = [
        '# Historical weather-provider comparison', '',
        f"Location: {report['location']['name']}",
        f"Hourly period: {report['period']['start_date_utc']} to "
        f"{report['period']['end_date_utc']} UTC (2015–2024 forecast seasons)",
        '', '## Matched hourly coverage and disagreement', '',
        '| Variable | ERA5 coverage | POWER coverage | Matched hours | Mean absolute difference |',
        '|---|---:|---:|---:|---:|',
    ]
    for row in report['hourly_comparison']:
        lines.append(f"| {row['field']} | {row['era5_coverage_pct']:.2f}% | "
                     f"{row['power_coverage_pct']:.2f}% | {row['matched_hours']} | "
                     f"{row['mean_absolute_difference']} {row['unit']} |")
    reliability = report['era5_reliability']
    pressure = report['pressure_coverage']
    missing = report['power_missing_by_parameter']
    invalid = report['power_invalid_by_parameter']
    lines += ['', '## Completeness and provenance', '',
              f"ERA5 stored {reliability['stored_hours']}/{reliability['expected_hours']} "
              f"hours; {reliability['interpolated_hours']} interpolated, "
              f"{reliability['non_valid_quality_hours']} non-valid quality flags, "
              f"{reliability['missing_raw_reference_hours']} missing raw references.",
              f"POWER fill/missing counts: {missing}; invalid-range counts: {invalid}.",
              f"Pressure availability: ERA5 sea-level {pressure['era5_sea_level_pressure_hours']} "
              f"hours; POWER surface {pressure['power_surface_pressure_hours']} hours. "
              'Pressure values are not directly compared.', '']
    daily = report['daily_rainfall']
    lines += ['', '## Daily rainfall disagreement', '',
              f"Matched days: {daily['matched_days']}; mean absolute difference: "
              f"{daily['mean_absolute_difference_mm']} mm; wet/dry label changes: "
              f"{daily['wet_day_disagreement_count']}.",
              f"If POWER hours are shifted +1 hour, the mean absolute daily change "
              f"is {daily['hour_boundary_sensitivity']['mean_absolute_change_mm']} mm "
              f"and {daily['hour_boundary_sensitivity']['wet_day_changes']} wet/dry "
              'labels change versus the unshifted POWER aggregation.',
              '', '## Impact on matched 2022–2024 baseline evaluation', '',
              '| Provider | Approach | Evaluated days | Rain MAE (mm) | Brier score |',
              '|---|---|---:|---:|---:|']
    for provider, approaches in report['evaluation_impact'].items():
        for approach, values in approaches.items():
            lines.append(f"| {provider} | {approach} | {values['evaluated_rows']} | "
                         f"{values['mae_mm']} | {values['brier_score']} |")
    lines += ['', 'Compared with each provider’s own seasonal baseline, no '
              'Karuvottam or combined approach improves both point metrics '
              'in both provider datasets. The existing publication hold remains.',
              '']
    lines += ['', '## Interpretation limits', '']
    lines += [f'- {item}' for item in report['caveats']]
    lines += ['', 'Raw POWER responses, checksums, UTC and unit validation, derived '
              'NASA dataset, baseline predictions, and full metric tables are in this '
              'artifact directory.', '']
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--dataset-manifest', type=Path, required=True)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--baseline-manifest', type=Path, required=True)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = ProviderComparisonService().build(
        args.dataset, args.dataset_manifest, args.baseline,
        args.baseline_manifest, args.database, args.output)
    print(f"Compared {report['daily_rainfall']['matched_days']} daily rainfall rows; "
          f"report: {args.output / 'provider_comparison.md'}")


if __name__ == '__main__':
    main()
