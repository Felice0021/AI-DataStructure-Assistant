"""Executable structure/citation checks. Not a proof of factual entailment."""
import json
import re
import unicodedata
from pydantic import ValidationError
from backend.v2.schemas.rag import AnswerDraft

CITATION=re.compile(r'\[S[1-9][0-9]*\]')
CITATION_LIKE=re.compile(r'\[[sS][^\]\n]*\]')
UNSUPPORTED_ACTION=re.compile(r'我(?:已经|已)?(?:运行|执行|访问|联网|浏览|查阅外部)|\bI (?:have )?(?:executed|ran|visited|browsed|searched the web)\b',re.I)
SOURCE_PROSE=re.compile(r'\b[\w.-]+\.(?:pdf|docx|txt)\b|第\s*\d+\s*页|\bpage\s+\d+\b',re.I)


class AnswerValidationError(Exception):pass


def no_duplicates(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('Duplicate JSON key')
        result[key]=value
    return result


def parse_draft(content,settings):
    try:size=len(content.encode()) if isinstance(content,str) else 0
    except UnicodeError:raise AnswerValidationError('invalid_output_unicode') from None
    if not isinstance(content,str) or not content.strip() or size>settings.generation_max_output_bytes:
        raise AnswerValidationError('invalid_output_budget')
    try:
        value=json.loads(content,object_pairs_hook=no_duplicates,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
        return AnswerDraft.model_validate(value)
    except (ValueError,TypeError,ValidationError,RecursionError):raise AnswerValidationError('invalid_output_schema') from None


def validate_answer(draft,evidence):
    allowed={e['citation_id'] for e in evidence}
    cited=CITATION.findall(draft.answer)
    listed=draft.used_source_ids
    if draft.status!='answered':
        if draft.answer.strip() or listed or cited:raise AnswerValidationError('invalid_refusal')
        return []
    if not draft.answer.strip() or not cited:raise AnswerValidationError('missing_citations')
    if len(set(listed))!=len(listed) or set(cited)!=set(listed) or not set(cited)<=allowed:
        raise AnswerValidationError('invalid_citations')
    if any(not CITATION.fullmatch(x) for x in listed) or any(not CITATION.fullmatch(x) for x in CITATION_LIKE.findall(draft.answer)):
        raise AnswerValidationError('invalid_citation_format')
    if any(unicodedata.category(c) in {'Cc','Cf','Cs'} and c not in '\n\t' for c in draft.answer):raise AnswerValidationError('invalid_output_unicode')
    if re.search(r'\[[sS]\s*[-+]?\d',CITATION.sub('',draft.answer)):raise AnswerValidationError('invalid_citation_format')
    if UNSUPPORTED_ACTION.search(draft.answer):raise AnswerValidationError('unsupported_execution_claim')
    if SOURCE_PROSE.search(draft.answer):raise AnswerValidationError('unsupported_source_metadata')
    return list(dict.fromkeys(cited))  # Repeated inline citations are valid; metadata list must be unique.
