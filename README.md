# SecureCallOps

SecureCallOps is a phone outreach app for teams that do not want to hand every caller the whole contact list.

The core rule is simple: a caller should only see the contact they are working on right now. Admins can still upload contacts, approve callers, and review outcomes.

## Why This Project Exists

Small organizations often start outreach work in shared spreadsheets. That is quick, but it also spreads names and phone numbers across inboxes, laptops, and chat channels. This app turns that spreadsheet into a controlled calling queue.

This project was originally built for a volunteer phone-banking campaign and later cleaned up and open-sourced.

This repository is a neutral open-source project and is not affiliated with any campaign, party, charity, or organization.

It works for:

- Nonprofits or charities calling supporters or beneficiaries.
- Civic and community groups running phone outreach.
- Unions, tenant groups, and mutual aid teams contacting members.
- Incident response or customer-success teams making careful calls.

## Security Features

- OTP-based sign-in for admins and callers.
- Separate admin and caller applications with separate session cookies.
- Contact names and phone numbers encrypted at rest with Fernet.
- Callers receive one active assignment at a time.
- Phone numbers are not rendered into the HTML DOM. Calls start through a server-side `tel:` redirect.
- Contact names are rendered as server-side PNG images rather than plain text.
- Server-enforced cooldown to reduce rapid contact enumeration.
- Content Security Policy, `nosniff`, `DENY` frame protection, and strict referrer policy.
- CSV formula-injection protection on exported results.
- Append-only call result table enforced by a PostgreSQL trigger.
- Non-root Docker container user.

## Architecture

The application is split into two FastAPI services:

- `app.phonebanking.main:app` runs the caller interface on port `8001`.
- `app.admin.main:app` runs the admin interface on port `8002`.

Both services use the same PostgreSQL database and read their settings from environment variables.

See [docs/architecture.md](docs/architecture.md) and [THREAT_MODEL.md](THREAT_MODEL.md) for the security design.

## Local Development

1. Copy `.env.example` to `.env`.
2. Generate a Fernet key:

```
python scripts/generate_fernet_key.py
```

3. Put the generated value in `FERNET_KEY`.
4. Keep `COOKIE_SECURE=false` for local HTTP development.
5. For local testing without SMTP, keep `DEV_OTP_LOG=true` and read sign-in codes from the service logs.
6. Start the stack:

```
docker compose up --build
```

7. Seed the first admin directly in PostgreSQL:

```sql
INSERT INTO pb_admin_users(email) VALUES ('you@example.com');
```

8. Open the services:
   - Caller app: `http://localhost:8001/pb/login`
   - Admin app: `http://localhost:8002/login`

To test email delivery locally, set `DEV_OTP_LOG=false` and use an SMTP sandbox.

## Running Tests

```
pip install -r requirements-dev.txt
pytest
```

## Contact CSV Format

Admin uploads expect a CSV with these columns:

```csv
name,phone
Alex Morgan,+447700900001
Sam Rivera,+447700900002
```

A sanitized example is provided at [samples/contacts.example.csv](samples/contacts.example.csv).

## Azure Deployment

The repo includes a Terraform starter in [infra/terraform](infra/terraform) for Azure:

- Azure Container Registry
- Azure Container Apps
- Azure Database for PostgreSQL Flexible Server
- Azure Key Vault
- Log Analytics

See [docs/azure-deployment.md](docs/azure-deployment.md).

## License

MIT. See [LICENSE](LICENSE).
