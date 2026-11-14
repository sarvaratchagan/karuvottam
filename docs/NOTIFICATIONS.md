# T9.3 — Email and message notifications

Notifications are opt-in and cover source-monitor health transitions for active IBTrACS, DMI and ONI. Health events include failed or never-run polls, overdue polls, stale index periods and unreadable monitor state. A recovery event is emitted when a source returns to `ok`. Repeated scans of the same health state do not queue duplicate messages. These are **data-source status notices**, not weather warnings or rain forecasts.

Run the database migration first:

```bash
.venv/bin/python -m karuvottam.database migrate
```

Configure SMTP over STARTTLS with `KARUVOTTAM_SMTP_HOST`, `KARUVOTTAM_SMTP_PORT` (default 587), `KARUVOTTAM_SMTP_FROM`, and optional `KARUVOTTAM_SMTP_USERNAME` / `KARUVOTTAM_SMTP_PASSWORD`. For a message gateway, set the operator-controlled `KARUVOTTAM_MESSAGE_WEBHOOK_URL` to an HTTPS endpoint accepting JSON `{ "text": "..." }`. Keep secrets in the service environment. No delivery happens during migration or rule creation.

Add explicit subscriptions. `all` can be replaced with `active`, `dmi`, or `oni`:

```bash
.venv/bin/python -m karuvottam.notifications add-rule --event source_health --source all --channel email --email operator@example.org
.venv/bin/python -m karuvottam.notifications add-rule --event source_recovery --source all --channel email --email operator@example.org
.venv/bin/python -m karuvottam.notifications add-rule --event source_health --source active --channel message
.venv/bin/python -m karuvottam.notifications list-rules
```

Rules can be `disable-rule ID` or `enable-rule ID`. Message destinations are a single environment-configured gateway rather than arbitrary URLs in the database. Email destinations are a single validated address per rule. Configure the gateway to handle any provider-specific authentication and recipient routing.

Schedule `scan` every 15 minutes and `send-due` every 5 minutes using the sample in [`deploy/source-monitor.cron.example`](../deploy/source-monitor.cron.example). `scan` reads the monitor state and queues transitions. `send-due` claims due deliveries with a ten-minute lease, sends at most 20 per invocation, and exits nonzero if a delivery attempt fails. Failure records contain an error **type**, not credentials or response bodies. Automatic retries start after five minutes and back off to a maximum of 24 hours. An interrupted worker's lease expires and the item becomes claimable again; a transport that accepted a message just before interruption may receive a duplicate, so receivers should tolerate duplicates.

Inspect the protected `/admin` page or use `list-deliveries`. To retry a failed item immediately after fixing the transport, run `retry ID` and then `send-due`. Rules and delivery history persist in SQLite. No live destinations or messages are configured by default. The sample cron is documentation only; the deployment operator installs it after supplying the SMTP or gateway configuration.
