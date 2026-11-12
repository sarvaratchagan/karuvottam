# T7.4 — Production deployment

This is a deployment recipe for one Linux host with a local SQLite database. The
repository supplies a Gunicorn WSGI entry point, systemd and nginx examples, and
readiness/liveness endpoints. It does not provision a public host or certificate.

## Prepare the host

Use a dedicated unprivileged service account. Install a supported Python version,
create a virtual environment, and install runtime requirements:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m karuvottam.database migrate
.venv/bin/python -m karuvottam.backup create --directory /mounted/offsite/karuvottam
```

Set `KARUVOTTAM_DATABASE_PATH`, `KARUVOTTAM_LOG_PATH` and
`KARUVOTTAM_WEATHER_RAW_DATA_DIR` to persistent, writable paths. Set location,
timezone, calendar anchor and weather provider variables for the deployment.
Keep `KARUVOTTAM_ADMIN_USERNAME`, `KARUVOTTAM_ADMIN_PASSWORD`, and any weather API
key in an operator-owned environment file outside the repository; make it readable
only by the service account. The [environment template](../.env.example) lists all
settings. Use absolute paths in production. Ensure database, WAL, logs and raw
archives have enough disk space. Restrict file permissions and back up the
database and raw archives separately.

For a foreground smoke test on the host:

```bash
.venv/bin/gunicorn --bind 127.0.0.1:8000 --workers 2 --threads 4 --timeout 60 --access-logfile - --error-logfile - wsgi:app
```

Gunicorn binds to loopback only. The WSGI entry point is `wsgi:app`; `app.py`'s
Flask development runner is for local work only. For a managed service, adapt
[`deploy/karuvottam.service.example`](../deploy/karuvottam.service.example), set
the paths and environment file, then enable it with systemd. Keep the database on
a local filesystem supported by SQLite, not a shared network mount.

## HTTPS and reverse proxy

Adapt [`deploy/nginx.conf.example`](../deploy/nginx.conf.example): replace the
domain and certificate paths, validate the nginx config, and enable it after the
certificate is valid. It redirects HTTP to HTTPS, terminates TLS, forwards only to
the loopback Gunicorn listener, limits request bodies, and sets HSTS. Expose only
ports 80/443 at the firewall. Do not publish port 8000. HTTP Basic administrator
credentials must travel only over HTTPS. Configure certificate renewal and test a
renewal before launch.

## Health, logs and alerting

- `GET /health/live` returns HTTP 200 while the WSGI worker can answer requests.
- `GET /health/ready` returns HTTP 200 only when the configured SQLite file is
  readable and its migration history matches this checkout; otherwise HTTP 503.
  It never creates a missing database and does not call an external weather API.
- Both responses contain only a status word and a request ID header; they do not
  expose paths, schema details or credentials. Monitor readiness through HTTPS.
- Application diagnostics use the redacted rotating log at `KARUVOTTAM_LOG_PATH`.
  Gunicorn access and error logs go to the service journal; nginx logs are set in
  its config. Correlate failures with `X-Request-ID`. Monitor service restarts,
  HTTP 5xx, disk space, backup age/checksum and certificate expiry.
- Install the [event/climate source monitor schedule](SOURCE_MONITORING.md) and
  connect its nonzero poll/check exits to host alerting. Share its persistent
  state path with the web process so `/events` and `/climate` show poll health.

Example checks after deployment:

```bash
curl --fail --silent --show-error https://example.org/health/live
curl --fail --silent --show-error https://example.org/health/ready
curl --head https://example.org/
```

## Pre-release checklist

1. Run `.venv/bin/python -m pip check`,
   `.venv/bin/python -m pip_audit -r requirements.txt --strict`, and
   `.venv/bin/python -m pytest -q`.
2. Verify the production environment file, secret permissions, site location,
   calendar anchor, weather provider, persistent directories and free disk space.
3. Apply migrations; confirm `/health/ready` is HTTP 200 before routing traffic.
4. Run the [backup and restore drill](BACKUP_RECOVERY.md); install and monitor the
   daily backup schedule on the production host.
5. Verify Gunicorn starts under the service account, listens only on loopback, and
   restarts after failure. Validate nginx config, HTTPS redirect, valid certificate,
   HSTS and external firewall rules.
6. Check `/`, `/calendar`, `/prediction`, `/observations`, and `/admin` through
   HTTPS. Confirm `/admin` rejects missing/invalid credentials. Confirm no debug
   traceback or secret appears in responses or logs.
7. Confirm liveness/readiness monitoring, logs, backup freshness, certificate
   renewal and alert recipients. Record the deployed revision and recovery contact.

Rollback: stop the service, restore the prior compatible application revision and
its verified database snapshot if migrations changed, rerun readiness and page
checks, then resume traffic. Keep the original database/WAL files until recovery
is verified. Review the migration history before any downgrade; migrations are
forward-only.
