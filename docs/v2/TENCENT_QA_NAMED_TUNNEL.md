# Tencent QA named tunnel

The QA hostname is `https://qa.dsassistant.cn`. Cloudflare routes it to Caddy
on `127.0.0.1:18900` using Host `qa.dsassistant.cn`. This QA entry shows the
application login page without Basic Auth. The original `sslip.io` entry retains
Basic Auth as a fallback. The API and PostgreSQL remain loopback-only.

QA disables public registration with `DS_V2_REGISTRATION_ENABLED=false` and
builds the frontend with `VITE_REGISTRATION_ENABLED=false` and `VITE_API_BASE`
empty for same-origin requests. Existing accounts are provisioned separately.
The backend enforces registration policy; hiding the UI is not sufficient.

On the QA Caddy proxy only, set `X-Forwarded-Proto` to `https` and overwrite
`X-Forwarded-For` with Cloudflare `CF-Connecting-IP`. The origin listener must
remain bound to loopback and reachable only by the local connector. Do not
trust client-supplied forwarding headers or expose this listener publicly.
Cloudflare same-zone Worker subrequests can affect the client IP header: review
Worker and header-transform rules whenever they change. Login limits remain
database-backed; cookies remain Secure and HttpOnly, with Origin and CSRF checks.

The named connector uses a dedicated non-login user and a private token file
with `--token-file`; never put token values in commands, logs or Git. Caddy
returns `Cache-Control: no-store, private` for the QA entry. Check Cloudflare
cache behavior, the origin listener and the IP trust boundary after changes.

Before deployment, save private backups of the Caddy and runtime files and keep
the previous release and frontend. Validate Caddy and test registration,
anonymous access, CSRF, forged forwarding headers, login and RAG citations.
On failure restore the previous release, runtime and Caddy config; reload Caddy
and restart the API, then verify the old HTTPS entry. Do not remove databases,
accounts, private files or volumes. The frontend and backend registration flags
must be deployed together. Browser tests from the server do not replace an
independent Windows test.
