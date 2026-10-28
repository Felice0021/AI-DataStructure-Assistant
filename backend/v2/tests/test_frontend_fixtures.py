"""Offline fixture contracts only: no app, settings, database or test-server imports."""
import builtins
from copy import deepcopy
import io
import json
from pathlib import Path
import re
import socket
import subprocess

from pydantic import BaseModel
import pytest

from backend.v2.schemas.auth import Credentials, CsrfResponse, ErrorResponse, UserEnvelope
from backend.v2.schemas.knowledge_base import KnowledgeBaseList
from backend.v2.schemas.rag import AnswerDraft, AnswerSource, AskRequest, AskResponse
from backend.v2.services.answer_validation import AnswerValidationError, validate_answer

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "docs/v2/fixtures"
MODELS = {
    "Credentials": Credentials, "CsrfResponse": CsrfResponse, "UserEnvelope": UserEnvelope,
    "KnowledgeBaseList": KnowledgeBaseList, "AskRequest": AskRequest,
    "AskResponse": AskResponse, "ErrorResponse": ErrorResponse,
}


def load(name):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            assert key not in result, f"Duplicate JSON key: {key}"
            result[key] = value
        return result
    return json.loads((FIXTURES / name).read_text(encoding="utf8"), object_pairs_hook=unique,
                      parse_constant=lambda _: pytest.fail("Non-finite JSON number"))


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Fixture tests forbid network, workers and credentials")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    for module in (builtins, io):
        original = module.open
        def guarded(file, *args, _open=original, **kwargs):
            if isinstance(file, (str, Path)) and Path(file).name in {".env", "credentials.json"}:
                return forbidden()
            return _open(file, *args, **kwargs)
        monkeypatch.setattr(module, "open", guarded)


def exact_fields(raw, model):
    """Response models normally ignore extras; recurse so nested extras fail too."""
    assert isinstance(raw, dict) and set(raw) == set(type(model).model_fields)
    for name, value in model.__dict__.items():
        if isinstance(value, BaseModel):
            exact_fields(raw[name], value)
        elif isinstance(value, list):
            for item, parsed in zip(raw[name], value):
                if isinstance(parsed, BaseModel):
                    exact_fields(item, parsed)


def check(model, raw):
    parsed = model.model_validate_json(json.dumps(raw, ensure_ascii=False), strict=True)
    exact_fields(raw, parsed)
    return parsed


def check_rag(raw, extended=False):
    body = dict(raw)
    if extended:
        error = check(ErrorResponse, {"error": body.pop("error")})
        assert error.error.code == body["reason"]
    parsed = check(AskResponse, body)
    if parsed.status == "answered":
        assert parsed.reason is None and parsed.answer and parsed.sources
        assert len({s.citation_id for s in parsed.sources}) == len(parsed.sources)
        for source in parsed.sources:
            assert re.fullmatch(r"[0-9a-f]{64}", source.content_hash)
            assert re.fullmatch(r"[0-9a-f]{64}", source.embedding_space_id)
            assert source.generation > 0 and source.index_revision > 0
        draft = AnswerDraft(status="answered", answer=parsed.answer,
                            used_source_ids=[s.citation_id for s in parsed.sources])
        assert validate_answer(draft, [s.model_dump() for s in parsed.sources])
    else:
        assert parsed.sources == []
        assert not re.search(r"\[[sS][^\]]*\]", parsed.answer or "")
        if parsed.status in {"validation_failed", "generation_unavailable"}:
            assert extended and parsed.answer is None
    return parsed


BODY_FILES = [
    ("auth-csrf.response.json", CsrfResponse),
    ("auth-login.request.json", Credentials),
    ("auth-login.response.json", UserEnvelope),
    ("auth-me.response.json", UserEnvelope),
    ("knowledge-bases.response.json", KnowledgeBaseList),
    ("rag-ask.request.json", AskRequest),
    ("rag-insufficient.request.json", AskRequest),
    ("rag-cloud-consent.request.json", AskRequest),
    ("rag-answered.response.json", AskResponse),
    ("rag-insufficient.response.json", AskResponse),
    ("rag-validation-failed.response.json", AskResponse),
    ("rag-generation-unavailable.response.json", AskResponse),
    *[(name + ".response.json", ErrorResponse) for name in (
        "unauthorized", "csrf-rejected", "forbidden", "cloud-consent-required",
        "knowledge-base-not-found", "service-unavailable")],
]


@pytest.mark.parametrize("name,model", BODY_FILES, ids=[name for name, _ in BODY_FILES])
def test_body_contract(name, model):
    raw = load(name)
    if model is AskResponse:
        check_rag(raw, extended="error" in raw)
    else:
        check(model, raw)


def test_index_inventory_and_openapi_fields():
    scenarios = load("index.json")
    api = json.loads((ROOT / "docs/v2/openapi.json").read_text(encoding="utf8"))
    assert len(scenarios) == 14 and len({s["id"] for s in scenarios}) == 14
    referenced = set()
    for scene in scenarios:
        assert set(scene) == {"id", "method", "path", "http_status", "request_file", "response_file", "response_contract"}
        matches = [item for path, item in api["paths"].items()
                   if re.fullmatch(re.sub(r"\{[^}]+\}", "[0-9a-f-]{36}", path), scene["path"])]
        assert len(matches) == 1
        operation = matches[0][scene["method"].lower()]
        status = str(scene["http_status"])
        if status not in operation["responses"]:
            # Runtime AuthError middleware and JSONResponse errors aren't declared on RAG.
            assert scene["path"] == "/api/v2/rag/ask" and status in {"403", "502", "503"}
        response = load(scene["response_file"])
        if status == "200":
            assert "error" not in response
            assert operation["responses"][status]["content"]["application/json"]["schema"]["$ref"].endswith("/" + scene["response_contract"])
        if scene["request_file"]:
            request = load(scene["request_file"])
            ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[1]
            check(MODELS[ref], request)
            referenced.add(scene["request_file"])
        referenced.add(scene["response_file"])
    assert referenced == {name for name, _ in BODY_FILES}
    assert {p.name for p in FIXTURES.glob("*.json")} == referenced | {"index.json"}


@pytest.mark.parametrize("identifier,status,code,message", [
    ("unauthorized", 401, "unauthorized", "Authentication required"),
    ("csrf-rejected", 403, "csrf_rejected", "CSRF verification failed"),
    ("forbidden", 403, "forbidden", "Insufficient permissions"),
    ("cloud-consent-required", 403, "cloud_consent_required", "Purpose-specific cloud consent required"),
    ("knowledge-base-not-found", 404, "knowledge_base_not_found", "Knowledge base not found"),
    ("validation-failed", 502, "invalid_citations", "Generated answer failed validation"),
    ("generation-unavailable", 503, "generation_disabled", "Generation unavailable"),
    ("service-unavailable", 503, "service_unavailable", "Service temporarily unavailable"),
])
def test_http_error_mapping(identifier, status, code, message):
    scene = next(s for s in load("index.json") if s["id"] == identifier)
    assert scene["http_status"] == status
    body = load(scene["response_file"])
    assert body["error"] == {"code": code, "message": message}
    if status == 502 or identifier == "generation-unavailable":
        assert body["status"] == ("validation_failed" if status == 502 else "generation_unavailable")
        assert scene["response_contract"] == "AskResponse+ErrorResponse"
        check_rag(body, extended=True)
    else:
        assert scene["response_contract"] == "ErrorResponse"
        check(ErrorResponse, body)


def test_synthetic_identity_scope_dates_and_placeholders():
    user = check(UserEnvelope, load("auth-me.response.json")).user
    assert load("auth-me.response.json") == load("auth-login.response.json")
    login = load("auth-login.request.json")
    assert login["email"] == user.email == "student.fixture@example.com"
    assert login["password"] == "MOCK_ONLY_NOT_A_REAL_PASSWORD"
    csrf = load("auth-csrf.response.json")["csrf_token"]
    assert csrf.startswith("MOCK_ONLY_") and not re.fullmatch(r"[0-9a-f]{64}", csrf)
    listed = check(KnowledgeBaseList, load("knowledge-bases.response.json"))
    assert listed.total == len(listed.items) == 2 and listed.offset == 0
    private, public = listed.items
    assert private.visibility == "private" and private.owner_id == user.id
    assert public.visibility == "public" and public.owner_id is None
    assert all(item.created_at.tzinfo and item.updated_at >= item.created_at for item in [user, *listed.items])
    request = check(AskRequest, load("rag-ask.request.json"))
    assert set(request.knowledge_base_ids) == {private.id, public.id}
    assert not any((request.allow_cloud, request.allow_cloud_rerank, request.allow_cloud_generation))
    answered = check_rag(load("rag-answered.response.json"))
    for source in answered.sources:
        check(AnswerSource, source.model_dump(mode="json"))
        assert source.knowledge_base_id == private.id and source.page_number is None
    for name, _ in BODY_FILES:
        raw = json.dumps(load(name))
        assert not re.search(r"sk-[A-Za-z0-9]{20,}|Bearer |/Users/|storage_key|Set-Cookie|access_token", raw)


@pytest.mark.parametrize("mutation", ["extra", "nested_extra", "missing", "null", "enum", "uuid", "type"])
def test_checker_rejects_contract_drift(mutation):
    body = deepcopy(load("rag-answered.response.json"))
    if mutation == "extra": body["http_status"] = 200
    if mutation == "nested_extra": body["sources"][0]["storage_key"] = "never-public"
    if mutation == "missing": del body["reason"]
    if mutation == "null": body["sources"] = None
    if mutation == "enum": body["answer_mode"] = "chat"
    if mutation == "uuid": body["sources"][0]["chunk_id"] = "not-a-uuid"
    if mutation == "type": body["rerank_applied"] = "false"
    with pytest.raises((ValueError, AssertionError)):
        check_rag(body)


def test_checker_rejects_forged_citation():
    body = deepcopy(load("rag-answered.response.json"))
    body["answer"] = "虚构引用[S99]"
    with pytest.raises(AnswerValidationError):
        check_rag(body)


def test_offline_guard_rejects_connections_processes_and_secret_files():
    for operation in (
        lambda: socket.create_connection(("127.0.0.1", 5433)),
        lambda: subprocess.Popen(["never-run"]),
        lambda: Path("deploy/v2/.env").read_text(),
        lambda: open("credentials.json"),
    ):
        with pytest.raises(AssertionError):
            operation()
