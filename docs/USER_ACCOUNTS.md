# T9.4 — User accounts and roles

Database accounts use salted `scrypt` password hashes; the database never stores cleartext passwords. The existing environment administrator remains an optional bootstrap login with the `admin` role. It takes precedence over a database username with the same spelling, and the operator CLI rejects creation of that username while the environment administrator is configured. All protected routes use HTTP Basic authentication, so deploy only behind HTTPS. No browser session or cookie is created.

Apply migration 009, then use the service account's local operator CLI. Passwords are prompted without appearing in shell history or the process list:

```bash
.venv/bin/python -m karuvottam.database migrate
.venv/bin/python -m karuvottam.accounts create analyst --role researcher
.venv/bin/python -m karuvottam.accounts create observer --role viewer
.venv/bin/python -m karuvottam.accounts list
.venv/bin/python -m karuvottam.accounts set-role analyst --role data-maintainer
.venv/bin/python -m karuvottam.accounts set-password analyst
.venv/bin/python -m karuvottam.accounts disable observer
.venv/bin/python -m karuvottam.accounts enable observer
```

| Role | Protected access |
|---|---|
| `viewer` | `/workspace` |
| `researcher` | `/workspace`, `/workspace/research` |
| `data-maintainer` | `/workspace`, `/workspace/data` |
| `admin` | All workspaces, `/workspace/accounts`, `/admin` |

Missing or invalid credentials receive 401; an authenticated role without permission receives 403. Disabled accounts and old passwords lose access immediately. If neither database accounts nor environment credentials exist, protected routes return 503. Account listings omit password hashes, and protected responses are marked `no-store`.

Existing public forecast, calendar, observation and evidence pages remain readable without an account. Ingestion, migrations, backups and account management are local operator CLI jobs protected by host file permissions, not web account roles. The role workspace exposes research and data-source status but does not grant shell access or modify weather data. An operator should keep at least one working administrator before disabling another; the environment bootstrap account is the recovery path.
