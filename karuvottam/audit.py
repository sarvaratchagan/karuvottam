"""Explicit operator actions and read-only audit history CLI."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from config import settings
from karuvottam.data_access import DataAccess, PredictionRunRecord


def generate_forecast_run(
    year: int, mode: str, *, actor: str, reason: str,
    location_id: int | None = None,
) -> PredictionRunRecord:
    """Persist a generated forecast and its audit event in one transaction."""
    if not 2015 <= year <= 2100 or mode not in ('aadi', 'margazhi'):
        raise ValueError('year or mode is outside the supported forecast range')
    if not actor.strip() or not reason.strip():
        raise ValueError('actor and reason are required')
    import app as application

    with application.DATA_ACCESS.transaction() as work:
        locations = work.locations.list_active()
        if location_id is not None:
            location = work.locations.get_active(location_id)
            if location is None:
                raise ValueError('location_id must identify an active location')
        else:
            location = next((item for item in locations
                             if item.name == settings.location_name
                             and abs(item.latitude - settings.latitude) < 0.000001
                             and abs(item.longitude - settings.longitude) < 0.000001), None)
            if location is None and not locations:
                location = work.locations.add(
                    name=settings.location_name, latitude=settings.latitude,
                    longitude=settings.longitude, elevation_m=settings.elevation_m,
                    timezone_name=settings.timezone_name,
                )
            elif location is None:
                raise ValueError('configured default location is not active; specify location_id')
        rules = work.locations.rules(location.id)
    profile = application.profile_from_location(location, rules)
    timeline, _ = application.build_prediction_context(year, mode, profile)
    source_window = application.build_cycle(year, profile)[f'{mode}_window']
    with application.DATA_ACCESS.transaction() as work:
        stored_window = work.karuvottam_windows.find(
            source_window.season_type,
            source_window.season_year,
            source_window.rule_version,
            location_id=location.id,
        )
        if stored_window is None:
            stored_event = work.lunar_events.find(source_window.trigger_event)
            if stored_event is None:
                stored_event = work.lunar_events.add(source_window.trigger_event)
            stored_window = work.karuvottam_windows.add(
                source_window, trigger_event_id=stored_event.id,
                location_id=location.id,
            )
        elif (
            stored_window.start_datetime_local
            != source_window.start_datetime_local.isoformat(timespec='seconds')
            or stored_window.end_datetime_local
            != source_window.end_datetime_local.isoformat(timespec='seconds')
        ):
            raise ValueError('stored source window differs from current calendar rule')
        return work.forecasts.add_timeline(
            timeline,
            input_window_id=stored_window.id,
            actor=actor,
            reason=reason,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description='Karuvottam operator audit actions')
    subparsers = parser.add_subparsers(dest='command', required=True)
    generate = subparsers.add_parser('generate-forecast')
    generate.add_argument('--year', type=int, required=True)
    generate.add_argument('--mode', choices=('aadi', 'margazhi'), required=True)
    generate.add_argument('--actor', required=True)
    generate.add_argument('--reason', required=True)
    generate.add_argument('--location-id', type=int)
    add_location = subparsers.add_parser('add-location')
    add_location.add_argument('--name', required=True)
    add_location.add_argument('--latitude', type=float, required=True)
    add_location.add_argument('--longitude', type=float, required=True)
    add_location.add_argument('--elevation-m', type=float)
    add_location.add_argument('--timezone', default='Asia/Kolkata')
    add_location.add_argument('--actor', required=True)
    add_location.add_argument('--reason', required=True)
    location_rules = subparsers.add_parser('set-location-rules')
    location_rules.add_argument('--location-id', type=int, required=True)
    location_rules.add_argument('--chithirai-reference', required=True)
    location_rules.add_argument('--rule-version', required=True)
    location_rules.add_argument('--margazhi-anchor-year', type=int, required=True)
    location_rules.add_argument('--margazhi-anchor-phase',
                                choices=('new_moon', 'full_moon'), required=True)
    location_rules.add_argument('--actor', required=True)
    location_rules.add_argument('--reason', required=True)
    ingest = subparsers.add_parser('ingest-weather')
    ingest.add_argument('--location-id', type=int, required=True)
    ingest.add_argument('--start-date', required=True)
    ingest.add_argument('--end-date', required=True)
    ingest.add_argument('--actor', required=True)
    ingest.add_argument('--reason', required=True)
    location = subparsers.add_parser('set-location-active')
    location.add_argument('--location-id', type=int, required=True)
    state = location.add_mutually_exclusive_group(required=True)
    state.add_argument('--active', action='store_true')
    state.add_argument('--inactive', action='store_true')
    location.add_argument('--actor', required=True)
    location.add_argument('--reason', required=True)
    history = subparsers.add_parser('list')
    history.add_argument('--limit', type=int, default=50)
    args = parser.parse_args()
    try:
        if args.command == 'generate-forecast':
            result = generate_forecast_run(
                args.year, args.mode, actor=args.actor, reason=args.reason,
                location_id=args.location_id,
            )
            print(json.dumps(asdict(result), ensure_ascii=False))
            return
        if args.command == 'ingest-weather':
            if not args.actor.strip() or not args.reason.strip():
                raise ValueError('actor and reason are required')
            start_date = date.fromisoformat(args.start_date)
            end_date = date.fromisoformat(args.end_date)
            access = DataAccess(settings.database_path)
            with access.transaction() as work:
                place = work.locations.get_active(args.location_id)
                if place is None:
                    raise ValueError('location_id must identify an active location')
            import app as application
            report = application.WEATHER_INGESTION_SERVICE.ingest(
                location_id=place.id, latitude=place.latitude,
                longitude=place.longitude,
                start_date=start_date, end_date=end_date,
            )
            with access.transaction() as work:
                work.audit.add(actor=args.actor, action='weather_ingested',
                               record_type='location', record_id=str(place.id),
                               reason=args.reason)
            print(json.dumps({
                'location_id': place.id,
                'fetched_hours': report.fetched_hours,
                'inserted_hours': report.inserted_hours,
                'existing_hours': report.existing_hours,
                'rejected_hours': report.rejected_hours,
                'raw_payload_reference': report.raw_payload_reference,
            }, ensure_ascii=False))
            return
        access = DataAccess(settings.database_path)
        with access.transaction() as work:
            if args.command == 'add-location':
                if not args.name.strip() or len(args.name) > 200:
                    raise ValueError('location name must contain 1–200 characters')
                if not -90 <= args.latitude <= 90 or not -180 <= args.longitude <= 180:
                    raise ValueError('latitude or longitude is out of range')
                try:
                    ZoneInfo(args.timezone)
                except ZoneInfoNotFoundError as exc:
                    raise ValueError('timezone is not available') from exc
                if not args.actor.strip() or not args.reason.strip():
                    raise ValueError('actor and reason are required')
                added = work.locations.add(
                    name=args.name.strip(), latitude=args.latitude,
                    longitude=args.longitude, elevation_m=args.elevation_m,
                    timezone_name=args.timezone,
                )
                work.locations.set_rules(
                    added.id, chithirai_reference=settings.chithirai_reference,
                    rule_version=settings.calendar_rule_version,
                    margazhi_anchor_year=settings.margazhi_alternation_anchor_year,
                    margazhi_anchor_phase=settings.margazhi_alternation_anchor_phase,
                )
                work.audit.add(actor=args.actor, action='location_added',
                               record_type='location', record_id=str(added.id),
                               reason=args.reason)
                print(json.dumps(asdict(added), ensure_ascii=False))
            elif args.command == 'set-location-rules':
                if not args.actor.strip() or not args.reason.strip():
                    raise ValueError('actor and reason are required')
                rules = work.locations.set_rules(
                    args.location_id,
                    chithirai_reference=args.chithirai_reference,
                    rule_version=args.rule_version,
                    margazhi_anchor_year=args.margazhi_anchor_year,
                    margazhi_anchor_phase=args.margazhi_anchor_phase,
                )
                work.audit.add(actor=args.actor, action='location_rules_updated',
                               record_type='location', record_id=str(args.location_id),
                               reason=args.reason)
                print(json.dumps(asdict(rules), ensure_ascii=False))
            elif args.command == 'set-location-active':
                if not args.actor.strip() or not args.reason.strip():
                    raise ValueError('actor and reason are required')
                changed = work.locations.set_active(
                    args.location_id, args.active,
                    actor=args.actor, reason=args.reason,
                )
                print(json.dumps({'changed': changed}))
            else:
                print(json.dumps(
                    [asdict(item) for item in work.audit.list_recent(limit=args.limit)],
                    ensure_ascii=False,
                ))
    except (ValueError, OSError, ZoneInfoNotFoundError) as exc:
        parser.exit(1, f'Audit error: {exc}\n')


if __name__ == '__main__':
    main()
