# Threat Model

## Scope

SecureCallOps handles names and phone numbers on behalf of people who have not consented to broad exposure. The assets that matter: contact names and phones, caller and admin identities, OTPs in flight, active sessions, and call outcomes.

## Trust Boundaries

- Browser to FastAPI service over HTTPS in production.
- FastAPI services to PostgreSQL over a private network where possible.
- FastAPI services to SMTP provider for OTP delivery.
- Admin users versus caller users.
- Cloud control plane versus application runtime.

## Key Risks and Controls

| Risk | Control |
| --- | --- |
| Callers enumerate all contacts | One active assignment per session and `FOR UPDATE SKIP LOCKED` queueing. |
| Caller views phone numbers in page source | Phone numbers are returned only through a server-side `tel:` redirect. |
| Contact data exposed if database is copied | Names and phones are encrypted with Fernet before storage. |
| Stolen session cookie | HttpOnly, Secure, SameSite=strict cookies with 12-hour expiry. |
| OTP brute force | Short OTP expiry, attempt limits, and per-hour request limits. |
| Login user enumeration | Login request returns the same response whether an email is authorized or not. |
| CSV formula injection | Exported CSV cells are prefixed when they begin with risky formula characters. |
| Tampering with call outcomes | PostgreSQL trigger prevents update/delete on call results. |
| Script injection exfiltrates data | Strict Content Security Policy and no phone numbers in DOM. |
| Container breakout impact | App runs as a non-root container user. |

## Residual Risks

- If the Fernet key is compromised, stored contact data can be decrypted.
- SMTP account compromise could expose OTPs.
- Screenshots or camera photos can still capture rendered contact names.
- Admins can export decrypted results, so admin access must be tightly controlled.
- The app currently uses email OTP only, not phishing-resistant MFA.

## Future Hardening

- Audit logs for admin exports, uploads, caller changes, and sign-in events.
- Rate limiting at ingress or the app layer.
- Automated dependency and container image scanning.
- Private networking between container apps and PostgreSQL rather than firewall rules.
- Database backup and restore runbooks with tested recovery procedures.
