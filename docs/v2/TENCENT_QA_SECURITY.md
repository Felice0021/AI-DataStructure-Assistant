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

As audited on 2026-11-07, the host lacked `newuidmap`, `newgidmap`, rootlesskit,
and a rootless engine; AppArmor restricted unprivileged user namespaces. These
are observations, not an installation recipe or evidence that the proposed
identity and runtime have been deployed. Existing `.env`, uploaded files and
database credentials remain private and must never be copied into image builds,
Git, screenshots or test logs.
