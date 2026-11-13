"""Bounded, server-owned conversation context; history is never retrieval evidence."""
from dataclasses import dataclass
import json
import re
from uuid import UUID

from sqlalchemy import select

from backend.v2.core.errors import AuthError
from backend.v2.models import Message
from backend.v2.services.context_builder import safe_text
from backend.v2.services import conversation_service

# Reviewed lexical resolver, deliberately limited. Unknown/ambiguous anaphora asks for clarification.
TOPICS = (
    ('AVL 树', r'(?<![A-Za-z0-9_])AVL(?![A-Za-z0-9_])(?:\s*树)?'),
    ('B+ 树', r'(?<![A-Za-z0-9_])B\s*\+\s*树'),
    ('B 树', r'(?<![A-Za-z0-9_])B\s*树'),
    ('二叉搜索树', r'二叉搜索树|二叉排序树|(?<![A-Za-z0-9_])BST(?![A-Za-z0-9_])'),
    ('二叉树', r'二叉树'),
    ('快速排序', r'快速排序|快排|(?<![A-Za-z0-9_])quicksort(?![A-Za-z0-9_])'),
    ('归并排序', r'归并排序|\bmerge\s*sort\b'),
    ('堆排序', r'堆排序|\bheap\s*sort\b'),
    ('冒泡排序', r'冒泡排序|\bbubble\s*sort\b'),
    ('插入排序', r'插入排序|\binsertion\s*sort\b'),
    ('BFS', r'(?<![A-Za-z0-9_])BFS(?![A-Za-z0-9_])|广度优先(?:搜索|遍历)'),
    ('DFS', r'(?<![A-Za-z0-9_])DFS(?![A-Za-z0-9_])|深度优先(?:搜索|遍历)'),
    ('Dijkstra', r'(?<![A-Za-z0-9_])Dijkstra(?![A-Za-z0-9_])|迪杰斯特拉'),
    ('栈', r'栈|(?<![A-Za-z0-9_])stack(?![A-Za-z0-9_])'),
    ('队列', r'队列|(?<![A-Za-z0-9_])queue(?![A-Za-z0-9_])'),
    ('链表', r'链表|\blinked\s*list\b'),
)
REFERENCE = re.compile(r'它|该(?:算法|结构|方法|树)|这(?:个|种)(?:算法|结构|方法|树)?|上述|前面|刚才|^(?:那|那么)|^(?:最坏|最好|平均)(?:情况|情况下)|^(?:时间|空间)复杂度(?:呢|怎么样|如何|[？?])')
COMPARISON = re.compile(r'不同|区别|相比|比较')
CITATION = re.compile(r'\[S\d+\]')


def topics(text):
    matches = [(m.start(), m.end(), name) for name, pattern in TOPICS for m in re.finditer(pattern, text, re.I)]
    # Longer matches own their span; do not count "栈" twice or B tree inside B+ tree.
    chosen = []
    for start, end, name in sorted(matches, key=lambda m: (-(m[1]-m[0]), m[0])):
        if not any(start < e and end > s for s, e, _ in chosen):
            chosen.append((start, end, name))
    return list(dict.fromkeys(name for _, _, name in sorted(chosen)))


def bounded(text, max_bytes):
    return safe_text(CITATION.sub('', text)).encode('utf8')[:max_bytes].decode('utf8', errors='ignore')


@dataclass(frozen=True)
class Turn:
    question_id: UUID
    answer_id: UUID
    request_id: str
    question: str
    answer: str
    resolved_query: str
    result: dict
    kb_ids: tuple

    def prompt(self):
        return {'user': bounded(self.question, 512), 'assistant': bounded(self.answer, 768)}


@dataclass(frozen=True)
class Plan:
    query: str
    turns: tuple[Turn, ...] = ()
    reason: str | None = None

    def prompt_history(self):
        return [turn.prompt() for turn in self.turns]

    def audit(self):
        return {'method': 'bounded-topic-rules-v1', 'resolved_query': self.query,
                'history_request_ids': [t.request_id for t in self.turns]}


def load_recent(session, user, conversation_id, kb_ids, settings, verify_session, check_result):
    conversation_service.get_owned(session, user, conversation_id)
    rows = session.scalars(select(Message).where(Message.conversation_id == conversation_id)
                           .order_by(Message.seq.desc()).limit(settings.conversation_max_turns * 2)).all()
    turns = []
    scope = {str(k) for k in kb_ids}
    for i in range(0, len(rows)-1, 2):
        answer, question = rows[i:i+2]
        meta = answer.metadata_json
        if (answer.role != 'assistant' or question.role != 'user' or answer.seq != question.seq + 1
                or not meta.get('request_id') or meta['request_id'] != question.metadata_json.get('request_id')
                or set(meta.get('knowledge_base_ids', [])) != scope
                or meta.get('result', {}).get('status') != 'answered'
                or not meta.get('result', {}).get('sources')):
            break
        try:
            check_result(session, user, meta['result'], settings, verify_session, kb_ids)
        except AuthError as error:
            if error.status == 401:
                raise
            break  # A stale/forbidden turn is a boundary, never skip it to resurrect older context.
        resolved = meta.get('context', {}).get('resolved_query', question.content)
        turn = Turn(question.id, answer.id, meta['request_id'], question.content, answer.content,
                    resolved, meta['result'], tuple(kb_ids))
        candidate = [turn, *reversed(turns)]
        if len(json.dumps([t.prompt() for t in candidate], ensure_ascii=False).encode()) > settings.conversation_history_max_bytes:
            break
        turns.append(turn)
    return tuple(reversed(turns))


def plan(query, turns, max_query_chars):
    explicit = topics(query)
    needs_context = bool(REFERENCE.search(query))
    # A complete named question may contain a later pronoun referring to its own subject.
    if explicit and not REFERENCE.match(query) and not re.search(r'(?:和|与|跟|同)它', query):
        needs_context = False
    if not needs_context:
        # Independent new topics do not inherit unrelated conversation content.
        relevant = tuple(t for t in turns if set(topics(t.resolved_query)) & set(explicit)) if explicit else ()
        return Plan(query, relevant)
    if not turns:
        return Plan(query, reason='conversation_context_required')
    anchors = topics(turns[-1].resolved_query)
    if len(anchors) != 1:
        return Plan(query, reason='conversation_context_ambiguous')
    anchor = anchors[0]
    if explicit and anchor not in explicit:
        if len(explicit) != 1 or not COMPARISON.search(query):
            return Plan(query, reason='conversation_context_ambiguous')
        rewritten = f'比较 {anchor} 与 {explicit[0]}：' + re.sub(r'^(?:那么|那)\s*', '', query)
    elif explicit:
        rewritten = query
    else:
        rewritten = re.sub(r'它|该(?:算法|结构|方法|树)|这(?:个|种)(?:算法|结构|方法|树)?|上述(?:算法|结构|方法)?', anchor, query)
        if rewritten == query:
            rewritten = f'{anchor}：{query}'
    if len(rewritten) > max_query_chars:
        raise AuthError(422, 'conversation_query_limit', 'Resolved question exceeds retrieval limit')
    return Plan(rewritten, turns)


def revalidate(session, user, conversation_id, turns, settings, verify_session, check_result):
    conversation_service.get_owned(session, user, conversation_id, for_update=True)
    for turn in turns:
        question = session.get(Message, turn.question_id)
        answer = session.get(Message, turn.answer_id)
        if (question is None or answer is None or question.content != turn.question or answer.content != turn.answer
                or answer.conversation_id != conversation_id or question.conversation_id != conversation_id
                or answer.metadata_json.get('result') != turn.result):
            raise AuthError(409, 'conversation_context_stale', 'Conversation context changed')
        check_result(session, user, turn.result, settings, verify_session, turn.kb_ids)
