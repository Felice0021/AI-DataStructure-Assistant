"""Owned topic folders and bounded, provenance-backed study notes.

Notes are *context hints*, never evidence. Every use rechecks the original
answer's KB access, citations and conversation/project ownership.
"""
import re
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session
from pydantic import ValidationError

from backend.v2.core.errors import AuthError, unauthorized
from backend.v2.models import Conversation, Message, Project, ProjectMemory, User
from backend.v2.schemas.conversation import ProjectCreate, ProjectUpdate
from backend.v2.services import conversation_context

MAX_PROJECTS = 30
MAX_MEMORY_NOTES = 6
MAX_MEMORY_BYTES = 1800


def get_owned(session: Session, user: User, project_id: UUID, *, for_update=False) -> Project:
    if not user.is_active:
        raise unauthorized()
    stmt = select(Project).where(Project.id == project_id, Project.user_id == user.id, Project.deleted_at.is_(None))
    if for_update:
        stmt = stmt.with_for_update()
    record = session.scalar(stmt)
    if record is None:
        raise AuthError(404, 'project_not_found', 'Project not found')
    return record


def list_owned(session: Session, user: User):
    if not user.is_active:
        raise unauthorized()
    return session.scalars(select(Project).where(Project.user_id == user.id, Project.deleted_at.is_(None))
                           .order_by(Project.created_at.asc(), Project.id.asc())).all()


def validate_sources(session: Session, user: User, ids, target_id=None):
    if len(ids) > 12 or len(set(ids)) != len(ids) or target_id is not None and target_id in ids:
        raise AuthError(422, 'invalid_memory_sources', 'Invalid project memory sources')
    for source_id in ids:
        get_owned(session, user, source_id)
    return [str(source_id) for source_id in ids]


def create(session: Session, user: User, data: ProjectCreate):
    if session.scalar(select(func.count()).select_from(Project)
                      .where(Project.user_id == user.id, Project.deleted_at.is_(None))) >= MAX_PROJECTS:
        raise AuthError(422, 'project_limit', 'Too many projects')
    sources = validate_sources(session, user, data.memory_source_ids)
    record = Project(user_id=user.id, title=data.title.strip(), description=data.description.strip(),
                     memory_source_ids=sources)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def update_owned(session: Session, user: User, project_id: UUID, data: ProjectUpdate):
    record = get_owned(session, user, project_id, for_update=True)
    if not data.model_fields_set:
        raise AuthError(422, 'empty_update', 'No project changes')
    if 'title' in data.model_fields_set:
        if data.title is None or not data.title.strip():
            raise AuthError(422, 'invalid_project_title', 'Invalid project title')
        record.title = data.title.strip()
    if 'description' in data.model_fields_set:
        if data.description is None:
            raise AuthError(422, 'invalid_project_description', 'Invalid description')
        record.description = data.description.strip()
    if 'memory_source_ids' in data.model_fields_set:
        if data.memory_source_ids is None:
            raise AuthError(422, 'invalid_memory_sources', 'Invalid project memory sources')
        record.memory_source_ids = validate_sources(session, user, data.memory_source_ids, project_id)
    record.updated_at = session.scalar(select(func.clock_timestamp()))
    session.commit()
    session.refresh(record)
    return record


def delete_owned(session: Session, user: User, project_id: UUID):
    record = get_owned(session, user, project_id, for_update=True)
    # Preserve conversations: deleted folder moves them back to ordinary history.
    session.execute(update(Conversation).where(Conversation.project_id == project_id)
                    .values(project_id=None))
    session.execute(delete(ProjectMemory).where(ProjectMemory.project_id == project_id))
    now = session.scalar(select(func.clock_timestamp()))
    record.deleted_at = now
    record.updated_at = now
    for other in list_owned(session, user):
        if project_id != other.id and str(project_id) in other.memory_source_ids:
            other.memory_source_ids = [source for source in other.memory_source_ids if source != str(project_id)]
            other.updated_at = now
    session.commit()


def own_notes(session: Session, user: User, project_id: UUID, settings, verify_session, checked_result):
    get_owned(session, user, project_id)
    rows = session.execute(select(ProjectMemory, Message, Conversation)
        .join(Message, Message.id == ProjectMemory.answer_message_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(ProjectMemory.project_id == project_id,
               Conversation.project_id == project_id, Conversation.user_id == user.id,
               Conversation.deleted_at.is_(None), Message.role == 'assistant')
        .order_by(ProjectMemory.created_at.desc(), ProjectMemory.id.desc()).limit(50)).all()
    verified = []
    for note, answer, _ in rows:
        meta = answer.metadata_json
        if note.summary != extract_summary(answer.content) or meta.get('result', {}).get('status') != 'answered':
            continue
        kb_ids = meta.get('knowledge_base_ids', [])
        if not kb_ids:
            continue
        try:
            checked_result(session, user, meta['result'], settings, verify_session, kb_ids)
        except AuthError as error:
            if error.status == 401:
                raise
            continue
        except (ValidationError, ValueError, TypeError):
            continue
        verified.append(note)
    return verified


def forget_note(session: Session, user: User, project_id: UUID, note_id: UUID):
    get_owned(session, user, project_id)
    record = session.scalar(select(ProjectMemory).where(ProjectMemory.id == note_id,
                                                      ProjectMemory.project_id == project_id))
    if record is None:
        raise AuthError(404, 'memory_not_found', 'Memory not found')
    session.delete(record)
    session.commit()


def extract_summary(answer: str) -> str:
    # Deterministic extraction: no second LLM call, no claim of student mastery.
    clean = re.sub(r'\[S\d+\]', '', answer)
    clean = re.sub(r'```[\s\S]*?```', ' ', clean)
    clean = re.sub(r'(?m)^\s*#{1,6}\s*|[*`_]', '', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean[:420].rstrip()


def remember(session: Session, conversation: Conversation, question: str, answer: Message):
    if conversation.project_id is None:
        return
    # Only called after the usual server-side final result/citation validation.
    if answer.metadata_json.get('result', {}).get('status') != 'answered':
        return
    summary = extract_summary(answer.content)
    if not summary:
        return
    project = session.scalar(select(Project).where(Project.id == conversation.project_id,
                                                  Project.user_id == conversation.user_id,
                                                  Project.deleted_at.is_(None)))
    if project is None:
        return
    topic = conversation_context.discourse_focus(question) or project.title
    session.add(ProjectMemory(project_id=project.id, answer_message_id=answer.id,
                              topic=topic[:100], summary=summary))


def load_notes(session, user, conversation_id, kb_ids, settings, verify_session, checked_result):
    from backend.v2.services.conversation_service import get_owned as get_conversation
    conv = get_conversation(session, user, conversation_id)
    if conv.project_id is None:
        return ()
    target = get_owned(session, user, conv.project_id)
    authorized = [target.id]
    for raw_id in target.memory_source_ids:
        try:
            source = get_owned(session, user, UUID(raw_id))
        except (ValueError, TypeError, AuthError):
            continue  # Revoked or removed share must never be silently used.
        authorized.append(source.id)

    rows = session.execute(select(ProjectMemory, Message, Conversation)
        .join(Message, Message.id == ProjectMemory.answer_message_id)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(ProjectMemory.project_id.in_(authorized),
               Conversation.user_id == user.id, Conversation.deleted_at.is_(None),
               Conversation.project_id == ProjectMemory.project_id,
               Message.role == 'assistant', Conversation.id != conversation_id)
        .order_by(ProjectMemory.created_at.desc(), ProjectMemory.id.desc())
        .limit(24)).all()
    notes = []
    total_bytes = 0
    for note, answer, source_conv in rows:
        meta = answer.metadata_json
        if (meta.get('result', {}).get('status') != 'answered'
                or set(meta.get('knowledge_base_ids', [])) != {str(k) for k in kb_ids}
                or note.summary != extract_summary(answer.content)):
            continue
        try:
            checked_result(session, user, meta['result'], settings, verify_session, kb_ids)
        except AuthError as error:
            if error.status == 401:
                raise
            continue
        except (ValidationError, ValueError, TypeError):
            continue
        candidate = {'id': str(note.id), 'topic': note.topic, 'summary': note.summary,
                     'source_project_id': str(source_conv.project_id)}
        length = len((candidate['topic'] + candidate['summary']).encode('utf8'))
        if total_bytes + length > MAX_MEMORY_BYTES:
            break
        notes.append(candidate)
        total_bytes += length
        if len(notes) >= MAX_MEMORY_NOTES:
            break
    return tuple(notes)


def revalidate_notes(session, user, conversation_id, notes, kb_ids, settings, verify_session, checked_result):
    if not notes:
        return
    # Recheck the exact same pointers and source allowlist before any cloud call/commit.
    current = load_notes(session, user, conversation_id, kb_ids, settings, verify_session, checked_result)
    available = {item['id']: item for item in current}
    if any(available.get(item['id']) != item for item in notes):
        raise AuthError(409, 'project_memory_changed', 'Project memory scope changed')
