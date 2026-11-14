"""Build a draft English UI catalog from a reviewed Tamil fragment list.

This is a maintainer utility only; requests never use an external translation
service. Review the generated JSON before adding it to the application.
"""

import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlencode


def batches(lines, limit=400):
    batch = []
    size = 0
    for line in lines:
        if batch and size + len(line) + 1 > limit:
            yield batch
            batch = []
            size = 0
        batch.append(line)
        size += len(line) + 1
    if batch:
        yield batch


def translate(lines):
    query = urlencode({'q': '\n'.join(lines), 'langpair': 'ta|en'})
    result = subprocess.run(
        ['curl', '-fsS', '--max-time', '20',
         'https://api.mymemory.translated.net/get?' + query],
        check=True, capture_output=True, text=True,
    )
    payload = json.loads(result.stdout)
    if payload.get('responseStatus') != 200 or payload.get('quotaFinished'):
        raise RuntimeError(payload.get('responseDetails') or 'translation quota reached')
    result = payload['responseData']['translatedText'].splitlines()
    if len(result) != len(lines):
        raise ValueError(f'Expected {len(lines)} translations, received {len(result)}')
    return result


def main():
    sources = [line for line in Path(sys.argv[1]).read_text().splitlines()
               if line and not line.startswith('[')]
    catalog = {}
    for group in batches(sources):
        for source, target in zip(group, translate(group)):
            catalog[source] = target.strip()
    Path(sys.argv[2]).write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
