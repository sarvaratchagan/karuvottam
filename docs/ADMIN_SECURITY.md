# T7.2 — Administration security

## Protected administration page

`/admin` is protected with HTTP Basic authentication. The optional bootstrap
credentials come from `KARUVOTTAM_ADMIN_USERNAME` and
`KARUVOTTAM_ADMIN_PASSWORD`; they are never placed in Flask configuration,
HTML, URLs, source control, or logs. Both values must be set together. The
username accepts 1–64 ASCII letters, digits, `.`, `_`, or `-`; the password
must be 16–256 UTF-8 bytes. Database-backed administrators can also access it.

When no account or bootstrap credentials exist, `/admin` is closed with HTTP 503
instead of using a default password. Missing or invalid credentials receive HTTP 401 and a Basic
challenge. Comparisons use constant-time byte comparison. The authentication
header is bounded and malformed Base64 is rejected. Administrator responses use
`Cache-Control: no-store`.

HTTP Basic credentials are only transport-safe behind HTTPS. Local development
binds to `127.0.0.1`; production deployment must terminate HTTPS before exposing
the route. T9.4 extends this boundary with database accounts and roles; see
[user accounts](USER_ACCOUNTS.md). The environment administrator remains a
bootstrap login when configured.

Example local request (do not put a real password in shell history):

```bash
curl --user "$KARUVOTTAM_ADMIN_USERNAME" http://127.0.0.1:5000/admin
```

`curl` prompts for the password when it is omitted from `--user`.

## Input and response controls

- Request bodies are limited by `KARUVOTTAM_MAX_REQUEST_BYTES` (default 1 MiB;
  allowed range 1 KiB–10 MiB).
- Query strings are limited to 4 KiB, 20 unique parameters, 64-character names,
  and 256-character values.
- Duplicate parameter names and ASCII control characters are rejected with HTTP
  400 so an input cannot be interpreted differently by different layers.
- Existing year, date range, mode, view, coordinates, timezone, CSV structure,
  weather range, and database constraints remain enforced at their domain
  boundaries.
- Database queries use bound parameters in the data-access layer.
- Every response sets a restrictive same-origin Content Security Policy,
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and
  `Referrer-Policy: no-referrer`.

## Runtime secrets and debug mode

`.env` and `.env.*` are ignored by Git except the blank `.env.example` template.
`Settings` hides the weather API key and administrator password from its `repr`.
Both secrets are registered with the T7.1 log redactor. Flask `DEBUG` is forced
off in application configuration, and the local runner explicitly uses
`debug=False` and `use_reloader=False`.

Generate a password with a password manager or a cryptographically secure local
tool. Do not reuse an API key or personal account password.

## Dependency review

The application has four direct runtime dependencies: Flask, Astronomy Engine,
python-dotenv, and certifi. Development dependencies include pytest and
`pip-audit`. Run the repeatable checks after every dependency change and before
release:

```bash
python -m pip check
python -m pip_audit -r requirements.txt --strict
pytest
```

`pip check` detects inconsistent installed packages. `pip-audit` checks the
resolved runtime requirements against the Python Packaging Advisory Database and
returns non-zero when a known vulnerability is found. A clean audit is evidence
for the audit date only; dependencies must be re-audited for every release.

Review recorded on 2026-10-29: `pip check` reported no broken requirements and
`pip-audit 2.10.1 --strict` reported no known vulnerabilities in the resolved
runtime set (Flask 3.1.3, Astronomy Engine 2.1.19, python-dotenv 1.2.4,
certifi 2026.10.23, and Flask's resolved transitive dependencies).
