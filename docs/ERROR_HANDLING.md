# T7.1 — Error handling and logging

## User-visible behavior

Every HTTP response includes an `X-Request-ID`. A valid caller-supplied ID
(`A-Z`, `a-z`, digits, `.`, `_`, `-`, at most 64 characters) is retained;
otherwise the application generates a random 32-character ID. Error pages show
this reference so an operator can find the matching diagnostic entry without
showing exception messages, SQL, provider responses, URLs, or stack traces.

| Failure | HTTP status | User action |
|---|---:|---|
| Missing page | 404 | Return to the home page |
| Unsupported method | 405 | Return to the home page |
| Database unavailable/operation failure | 503 | Retry after a short delay |
| Weather transport/provider failure | 503 | Retry after a short delay |
| Unexpected application failure | 500 | Give the request ID to the operator |

The Tamil error template retains the same skip link, document language,
viewport, single main landmark, and single primary heading as the main UI.

## Diagnostic log

The default log is `data/logs/karuvottam.log`. It rotates at 2 MiB and retains
five older files. `KARUVOTTAM_LOG_PATH` selects another path and
`KARUVOTTAM_LOG_LEVEL` accepts `DEBUG`, `INFO`, `WARNING`, `ERROR`, or
`CRITICAL`.

The formatter redacts configured API-key values and credential-shaped text such
as `apikey=`, `api_key:`, `token=`, `password=`, `secret=`, Authorization values,
and Bearer credentials from both messages and exception tracebacks. Request
handlers deliberately log only request ID, method, path, and exception type;
they do not log query strings, request bodies, response bodies, or provider
URLs. Automated tests verify message and traceback redaction.

## Recovery procedure

### Weather API failure

1. The client retries transport failures, HTTP 429, and HTTP 5xx using bounded
   exponential backoff; a provider `Retry-After` value is honored up to 60 s.
2. Retry logs contain provider/model, status, attempt, and delay only.
3. A successful retry continues normally. Exhaustion raises a typed failure and
   the web layer returns 503 with a request ID.
4. Check network/provider health and configuration, then rerun the same
   ingestion. Raw payload storage is content-addressed and database ingestion is
   idempotent, so a retry does not duplicate accepted observations.

### Database failure

1. The data-access transaction rolls back on integrity, SQLite, and application
   exceptions; tests verify that partial writes are not committed.
2. Read-only dashboard, calendar, forecast-input, and observation-inspection
   services already convert expected data-access outages to documented degraded
   or unavailable states where possible.
3. A database error that reaches the web boundary returns 503 and is correlated
   with the redacted diagnostic log.
4. Check file permissions, free space, database health, and migrations. Restore
   service and repeat the operation; never edit the SQLite file while the app is
   writing.

Do not paste `.env` values, API keys, database contents, or full request URLs
into issue reports. Share the request ID and the smallest relevant redacted log
section instead.
