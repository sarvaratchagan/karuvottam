"""Print distinct Tamil text/attribute fragments on representative pages."""

from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import app
from karuvottam.security import AdminAuthenticator

TAMIL = re.compile(r'[\u0b80-\u0bff]')


class Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.strings = Counter()

    def handle_data(self, data):
        value = ' '.join(data.split())
        if TAMIL.search(value):
            self.strings[value] += 1

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if value and TAMIL.search(value):
                self.strings[f'[{key}] {value}'] += 1


def main():
    import base64
    auth = app.extensions['admin_authenticator']
    app.extensions['admin_authenticator'] = AdminAuthenticator(
        'inventory', 'inventory-password-long')
    token = base64.b64encode(b'inventory:inventory-password-long').decode()
    paths = ('/', '/calendar?year=2026',
        '/prediction?year=2026&mode=aadi&view=day',
        '/prediction?year=2026&mode=aadi&view=week',
        '/prediction?year=2026&mode=margazhi&view=month',
        '/observations', '/events?year=2025', '/climate',
        '/workspace', '/workspace/research', '/workspace/data',
        '/workspace/accounts', '/admin', '/not-a-route')
    collector = Collector()
    try:
        with app.test_client() as client:
            for path in paths:
                response = client.get(path, headers={'Authorization': f'Basic {token}'})
                if response.mimetype == 'text/html':
                    collector.feed(response.get_data(as_text=True))
    finally:
        app.extensions['admin_authenticator'] = auth
    for value in sorted(collector.strings):
        print(value)


if __name__ == '__main__':
    main()
