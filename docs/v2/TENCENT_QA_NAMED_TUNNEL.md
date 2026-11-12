# Tencent QA named tunnel

The fixed QA hostname is `https://qa.dsassistant.cn`. Cloudflare routes this
hostname to `http://127.0.0.1:18900` with HTTP Host Header `qa.dsassistant.cn`.
This loopback listener belongs to Caddy and requires the existing Basic Auth
before proxying `/api/v2/*` to the QA API. Caddy serves the production frontend
and sends `Cache-Control: no-store, private`. Browser-to-Cloudflare transport
uses HTTPS; connector-to-Caddy HTTP stays on loopback. Keep the original HTTPS
endpoint as a rollback route.

The named connector runs as non-login user `ds-v2-tunnel` using
`ds-v2-qa-tunnel.service`. Its server-local token file is owned by root and
readable only by the service group. Never place token contents in commands,
logs, Git or reports. The unit uses `--token-file`. Install cloudflared from
an authenticated official source and provision the private file securely.

Set `DS_V2_ALLOWED_ORIGINS` in the private systemd environment file to a JSON
array containing exactly the original HTTPS origin and `https://qa.dsassistant.cn`.
Do not use a wildcard. `run.sh` defaults to the existing single origin when
this variable is absent. Continue enforcing Secure cookies, Origin and CSRF.

Check the connector, Caddy, API and Workers with `systemctl is-active`; verify
that the public endpoint returns 401 before credentials, then test login,
citations, refusal and logout. Server-side tests do not replace independent
Windows browser acceptance. Verify Cloudflare does not cache private responses.

For rollback, stop the named-tunnel service, restore backed-up Caddy and runtime
configuration, validate Caddy before reloading, and verify the old HTTPS origin.
Do not delete the database, file storage or volumes.
