# Security Policy

SecureCallOps can handle real names and phone numbers, so treat any real deployment as sensitive.

## Supported Versions

Security fixes will land on `main` unless this project adds release branches later.

## Reporting a Vulnerability

If you find a vulnerability, please do not open a public issue with exploit details. Contact the maintainer privately and include:

- A clear description of the issue.
- Steps to reproduce.
- Potential impact.
- Suggested fix, if known.

## Deployment Responsibilities

If you run this app, you are responsible for:

- Rotating `FERNET_KEY`, database passwords, SMTP credentials, and cloud credentials when needed.
- Keeping Python dependencies and base images patched.
- Restricting admin access to trusted operators.
- Reviewing logs for sensitive data before enabling broad log access.
- Running the app behind HTTPS in production.
- Backing up PostgreSQL securely.

## Before Deploying Your Own Copy

- Run secret scanning against your working tree and git history.
- Check that no real contact CSVs, exports, screenshots, emails, phone numbers, or cloud resource IDs are committed.
- Verify `.env`, database dumps, private keys, and local state directories are ignored.
- Prefer a fresh public repository if the private history ever contained sensitive data.
