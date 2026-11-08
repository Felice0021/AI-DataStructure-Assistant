# Tencent QA: parser isolation review

The current QA deployment is a draft and is not ready for production. Its API,
parser worker, and embedding worker run as `ubuntu`; the audited host grants
that account unrestricted passwordless sudo. The parser's `sudo docker`
wrapper therefore grants effective host-root capability, regardless of the
network, filesystem, and resource flags applied to the normal parser container.
Do not treat the wrapper or membership in the Docker group as isolation.

The parser image is built with `backend/v2` as its build context. Its Dockerfile
copies only the parser entry point, error definitions, chunking, file validation,
and text extraction modules. On the QA server an isolated synthetic context test
checked that `.env` and `.key` canaries did not enter the image layers; the
existing container tests for TXT, PDF, and DOCX all passed against the reduced
image. These checks do not establish that arbitrary credentials cannot appear
elsewhere in a base image or build cache.

Before replacing the current service, provision a dedicated unprivileged service
identity with no sudo or rootful Docker socket access. Evaluate a separately
owned rootless engine, its subordinate UID/GID mappings, AppArmor policy,
systemd cgroup delegation, resource-limit enforcement, and bind-mount access.
The dedicated identity also needs narrowly scoped read access to the application
configuration and file storage; it must not inherit access to the `ubuntu` home
directory or the existing rootful Docker socket. Preserve the current PostgreSQL
container and data volumes. Verify failure is closed when the rootless socket or
resource controls are unavailable, then run real isolated parsing, indexing, RAG,
cross-user authorization, restart and rollback tests before changing QA traffic.

On 2026-11-08 Ubuntu's Podman and uidmap packages were installed and the separate
`ds-v2-parser` identity was provisioned with no sudo and no Docker group. A
synthetic TXT was parsed successfully with rootless Podman. Inside the container,
`memory.max` was 268435456 and `pids.max` was 16; the host reported systemd
cgroup v2. This identity could not write the rootful Docker socket or traverse
`/home/ubuntu`. Existing QA services were not switched to that identity.

The remaining integration blocker is material: `LocalFileStorage.directory()`
and `open()` require the directory and file owner to equal the service UID and
their modes to be private. Merely adding ACLs for a separate worker is therefore
not sufficient. Design and test a secure, reversible storage and credential
access boundary before switching services; do not relax these checks merely to
make the worker start. AppArmor restricts unprivileged user namespaces on the
host, although the isolated rootless Podman test above succeeded without changing
that kernel setting.

The separate server-side Chromium test on 2026-11-08 passed HTTPS page load,
application login, knowledge-base selection, an answered response with matching
`[S1]`, insufficient-evidence refusal, and logout followed by a 401. Its eight
observed API requests used same-origin HTTPS and it made no MSW worker request.
This was a server-side browser test, not an independent-network acceptance.
Existing `.env`, uploaded files and database credentials remain private and
must never be copied into image builds, Git, screenshots or test logs.
