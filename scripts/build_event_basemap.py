"""Extract the small, local T8.2 basemap from Natural Earth GeoJSON files.

Usage: python scripts/build_event_basemap.py COUNTRIES.geojson STATES.geojson
The inputs are Natural Earth's ne_50m_admin_0_countries and
ne_50m_admin_1_states_provinces GeoJSON distributions.
"""

import json
import sys
from pathlib import Path


COUNTRIES = {'India', 'Sri Lanka', 'Pakistan', 'Bangladesh', 'Myanmar', 'Maldives'}
STATES = {
    'Tamil Nadu', 'Kerala', 'Karnataka', 'Andhra Pradesh', 'Telangana',
    'Goa', 'Maharashtra', 'Odisha', 'Puducherry', 'Lakshadweep',
}


def rings(geometry):
    polygons = (
        [geometry['coordinates']] if geometry['type'] == 'Polygon'
        else geometry['coordinates']
    )
    return [
        [[round(lon, 3), round(lat, 3)] for lon, lat in ring]
        for polygon in polygons for ring in polygon
    ]


def main(country_file: Path, state_file: Path) -> None:
    countries = json.loads(country_file.read_text())['features']
    states = json.loads(state_file.read_text())['features']
    result = {
        'source': 'Natural Earth 1:50m admin-0 countries and admin-1 states/provinces',
        'countries': [
            {'name': feature['properties']['ADMIN'], 'rings': rings(feature['geometry'])}
            for feature in countries if feature['properties'].get('ADMIN') in COUNTRIES
        ],
        'states': [
            {'name': feature['properties']['name'], 'rings': rings(feature['geometry'])}
            for feature in states
            if feature['properties'].get('admin') == 'India'
            and feature['properties'].get('name') in STATES
        ],
    }
    output = Path(__file__).resolve().parents[1] / 'karuvottam' / 'event_basemap.json'
    output.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')) + '\n')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: build_event_basemap.py COUNTRIES.geojson STATES.geojson')
    main(Path(sys.argv[1]), Path(sys.argv[2]))
