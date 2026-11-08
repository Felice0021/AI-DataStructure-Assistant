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

## Shared-UID candidate, not yet a service cutover

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
indexing, RAG citations and cross-account authorization. This evidence does not
mean that the live QA services were switched. The existing QA database role was
observed to be a PostgreSQL superuser; introduce a least-privileged application
role and verify permissions before handing its credentials to a new service.
The same isolated systemd chain also passed with a newly created test database
role lacking superuser and database-creation privileges. The root filesystem
was verified read-only; Podman provides a writable temporary filesystem at
`/tmp`, bounded by the container memory limit. An invalid runtime directory was
rejected, but that test alone does not prove every possible engine failure mode.
