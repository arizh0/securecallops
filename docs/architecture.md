# Architecture

SecureCallOps uses two small FastAPI services and a shared PostgreSQL database.

## Services

| Service | Module | Default Port | Responsibility |
| --- | --- | --- | --- |
| Caller UI | `app.phonebanking.main:app` | `8001` | Caller login, contact assignment, call initiation, outcome submission. |
| Admin UI | `app.admin.main:app` | `8002` | Admin login, contact upload, caller management, stats, CSV export. |
| PostgreSQL | `app/sql/phonebanking_schema.sql` | `5432` | Encrypted contacts, sessions, assignments, OTPs, and call results. |

Both FastAPI services expose `/healthz` for container and platform health checks.

## Data Flow

1. Admin seeds authorized admins directly in PostgreSQL.
2. Admin signs in with email OTP.
3. Admin uploads `name,phone` CSV.
4. The app encrypts name and phone before inserting contacts.
5. Admin authorizes caller email addresses.
6. Caller signs in with email OTP.
7. Caller requests the next contact.
8. The server assigns one available contact and stores the assignment.
9. Caller views the name as a generated PNG and initiates a phone call through a `tel:` redirect.
10. Caller submits an outcome.
11. Admin reviews dashboard data or exports results.

## Security Design Choices

- Admin and caller services are split so their cookies, UI surface, and operational roles stay separate.
- Contact fields are encrypted at the app layer rather than relying on disk or database encryption alone.
- Phone numbers are kept out of HTML, so browser extensions, page source, and screenshots expose less.
- PostgreSQL row locking stops two callers from getting the same contact at the same time.
- Call results are append-only; a PostgreSQL trigger blocks any updates or deletes.

## Local Runtime

`docker-compose.yml` starts PostgreSQL, the caller service, and the admin service. The same image is used for both app services; `APP_MODULE` selects which FastAPI module starts.
