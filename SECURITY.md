# Security

Do not include keys or private model output in public issues. Reports contain endpoint output and may contain private data even though known supplied credentials are redacted. Use environment variables for credentials; URL credentials and redirects are rejected. HTTP credentials are accepted only on loopback.

This CLI contacts the endpoint the user supplies. It is not a hosted multi-tenant request proxy. Do not expose it as a public URL-fetch service without additional network controls. Synthetic sandbox servers bind to loopback and stop after the command.

For a sensitive issue, use GitHub's private vulnerability reporting if enabled. Otherwise open an issue requesting a private contact channel without posting exploit secrets. No guaranteed response time or security certification is claimed.
