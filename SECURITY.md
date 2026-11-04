# Security policy

SIGNALWATCH is an experimental **local-only** astronomical research service; it has no user account management or internet-grade authentication. Do **not** expose it to the public Internet as-is.

## Reporting issues

Please do not post live credentials, sensitive device details, unredacted private recordings, or proof-of-concept attack payloads in public issues. For a security-sensitive concern, contact the maintainers through the private security-reporting mechanism offered by the repository if enabled. If not enabled, request a private contact channel without publishing exploit material.

## Operational guidance

- Keep the FastAPI server bound to `127.0.0.1` or on a trusted private network.
- `SIGNALWATCH_WRITE_TOKEN` protects only supported mutation endpoints. It is **not** a complete authentication or authorization system.
- Deployments behind a reverse proxy need TLS, authentication, authorization, CSRF protections, rate limiting, auditing, and secure secret handling.
- Do not commit `data/`, raw receiver recordings, tokens, or SQLite database files.
- Review external-data rights and sanitize any operator-supplied recordings before sharing.
