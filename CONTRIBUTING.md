# Contributing

Pull requests welcome. The most useful contributions are security fixes, tests, accessibility improvements, docs, and deployment notes.

## Development Guidelines

- Keep real personal data out of the repository.
- Keep pull requests small when you can.
- Preserve the separation between admin and caller services.
- Do not log plaintext contact names, phone numbers, OTPs, or session tokens.
- Keep infrastructure examples generic and free of real subscription IDs, tenant IDs, resource names, or credentials.

## Local Checks

Before opening a pull request:

```powershell
python -m compileall app scripts
docker compose config
```

If Docker is available, also run:

```powershell
docker build -t securecallops:local .
```
