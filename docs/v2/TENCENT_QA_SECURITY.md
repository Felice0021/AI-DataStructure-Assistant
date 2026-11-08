# Tencent QA: parser isolation review

The QA deployment is a draft and is not ready for production. Before the
cutover recorded below, its API, parser and embedding processes ran as `ubuntu`,
which has unrestricted passwordless sudo. The old parser's `sudo docker`
wrapper granted effective host-root capability regardless of the normal
container's sandbox flags. Do not treat that wrapper or membership in the
Docker group as isolation.

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

The integration constraint is material: `LocalFileStorage.directory()`
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

## Shared-UID QA deployment

The candidate unit runs API, parser and embedding as `ds-v2-parser`, which has
no sudo or rootful Docker socket access. The three processes share an OS UID;
this does not isolate their access to application data from each other. Source
and virtualenv trees must be root-owned and not writable or replaceable by that
UID. The settings file must be private to root and this service group. Keep the
file storage root and its files owned by the service UID with modes 0700/0600;
never weaken `LocalFileStorage` ownership checks.

The Docker-compatible parser wrapper calls only local, rootless Podman and
requires cgroup v2, systemd and delegated CPU, memory and PID controllers. It
checks effective limits in a no-network, read-only probe container before each
parse and does not pull an image or fall back to rootful Docker. A missing
engine, image or failed check must fail the job closed. Enable user lingering,
configure subordinate UID/GID ranges and pre-load the pinned parser image in
the service user's image store before starting the worker.

The template expects root-managed `/opt/ds-v2-qa/current` and a private
`/etc/ds-v2-qa/runtime.env` containing `DS_V2_QA_ORIGIN`, `DS_V2_DB_NAME`,
`DS_V2_FILE_STORAGE_ROOT` and `DS_V2_PYTHON`; database credentials belong only
in a private server-local settings file, never in the repository. Before any
cutover, test the exact release and service units against an isolated database
and a hash-verified private storage copy, including parsing, indexing, RAG,
access control and fail-closed behavior. Retain the old unit, configuration and
storage intact. Stop only the three application services for a final consistent
copy, verify every file, switch the root-managed release and unit configuration,
then run authenticated HTTPS tests. On failure, stop the new units, restore the
previous unit and configuration, reload systemd and restart the old services;
do not remove either storage tree or change the database during rollback.
Database and application writes during a failed cutover require reconciliation;
do not roll back storage after accepting new uploads without a verified plan.

An isolated 2026-11-08 experiment ran three systemd processes as UID 1002,
restored a QA backup into a separate loopback PostgreSQL container and opened a
hash-verified storage copy with the unchanged ownership checks. A real HTTP
smoke run using rootless Podman and deterministic providers passed parsing,
indexing, RAG citations and cross-account authorization. The original QA
database role was observed to be a PostgreSQL superuser. A separate restricted
QA runtime role was created without superuser or database-creation privileges;
the original role and its credentials were retained for administration and
rollback. Schema migrations must run under an appropriately privileged
administrative role, and privileges on newly created objects must be reviewed.
The same isolated systemd chain also passed with a newly created test database
role lacking superuser and database-creation privileges. The root filesystem
was verified read-only; Podman provides a writable temporary filesystem at
`/tmp`, bounded by the container memory limit. An invalid runtime directory was
rejected, but that test alone does not prove every possible engine failure mode.

The QA services were switched on 2026-11-08 after stopping the QA entry point
and all three application processes. The original systemd unit was retained at
`/etc/ds-v2-qa/rollback-original.service`, and the original `ubuntu` settings and
storage were left intact. The final service-owned storage copy was checked for
matching SHA-256 hashes before starting the new units. API, parser and embedding
then ran as UID 1002; the existing QA user's ready document, RAG citation and
cross-user denial passed, as did server-side TLS and site authentication. The
service UID could not use sudo, access the rootful Docker socket or read the
student credential file. This is a service cutover, not a reboot or external
network test. The remaining rotation, reboot-recovery and independent-network
TLS acceptance have not been performed as part of this change.

For rollback, first stop QA traffic and the three application units. Since the
old storage copy becomes stale after the cutover, reconcile every newly created
object and any database changes before restoring the old unit; do not overwrite
an existing object or discard either storage tree. Once reconciliation is
verified, restore the saved unit, reload systemd, restart the original services
and validate existing document access before reopening QA traffic. The saved
unit alone is insufficient for a safe rollback after new uploads.
