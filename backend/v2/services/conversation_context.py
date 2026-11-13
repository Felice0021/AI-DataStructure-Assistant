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
from backend.v2.services.tree_inputs import operation_sequence, first_insert_count

# Reviewed lexical resolver, deliberately limited. Unknown/ambiguous anaphora asks for clarification.
TOPICS = (
    ('AVL 树', r'(?<![A-Za-z0-9_])AVL(?![A-Za-z0-9_])(?:\s*树)?'),
    ('红黑树', r'红黑树|red[ -]?black\s*tree|(?<![A-Za-z0-9_])RB\s*tree(?![A-Za-z0-9_])'),
    ('B+ 树', r'(?<![A-Za-z0-9_])B\s*\+\s*树'),
    ('B 树', r'(?<![A-Za-z0-9_])B\s*树'),
    ('二叉搜索树', r'二叉搜索树|二叉排序树|(?<![A-Za-z0-9_])BST(?![A-Za-z0-9_])'),
    ('二叉树', r'二叉树'),
    ('快速排序', r'快速排序|快排|(?<![A-Za-z0-9_])(?:quicksort|Lomuto|Hoare)(?![A-Za-z0-9_])'),
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
CASE_FOLLOWUP = re.compile(r'^(?:最好|平均|最坏)(?:(?:情况|情况下))?(?:呢|如何|怎么样)?[？?。\s]*$')
ROTATION_REFERENCE = re.compile(r'(?<![A-Za-z0-9_])(?:LL|RR|LR|RL)(?![A-Za-z0-9_]).*(?:失衡|旋转|树形)', re.I)
PARTITION_VARIANT = re.compile(r'(?<![A-Za-z0-9_])(Lomuto|Hoare)(?![A-Za-z0-9_])', re.I)
TOPIC_SWITCH = re.compile(r'换个话题|换一个话题|另一个问题|改讲|现在(?:讨论|讲)|接下来(?:讨论|讲)')
COMPARISON = re.compile(r'不同|区别|相比|比较')
CITATION = re.compile(r'\[S\d+\]')
MODIFICATION = re.compile(r'^(?:那|那么)?(?:应该|应当|要)?怎么(?:修改|修正)|^(?:那|那么)?(?:应该|应当|要)?如何(?:修改|修正)')
NEXT_INSERT = re.compile(r'^(?:请)?继续(?:展示|演示)?下(?:一)?次插入[。？！?！\s]*$')
STEP = re.compile(r'第([0-9]+|[一二三四五六七八九十])步')
FUNCTION = re.compile(r'\b(?:int|void|bool|char|float|double|Node|TreeNode|ListNode)\b\s*[*&]?\s*(\w+)\s*\([^)]*\)\s*\{|\bdef\s+(\w+)\s*\(')


def topics(text):
    matches = [(m.start(), m.end(), name) for name, pattern in TOPICS for m in re.finditer(pattern, text, re.I)]
    # Longer matches own their span; do not count "栈" twice or B tree inside B+ tree.
    chosen = []
    for start, end, name in sorted(matches, key=lambda m: (-(m[1]-m[0]), m[0])):
        if not any(start < e and end > s for s, e, _ in chosen):
            chosen.append((start, end, name))
    return list(dict.fromkeys(name for _, _, name in sorted(chosen)))


def discourse_focus(question):
    """An explicit focus or a unique independent subject, never the first item in a comparison."""
    clauses=re.split(r'[？?。；;，,\n]',question)
    emphasized=[];subjects=[]
    for clause in clauses:
        focus=re.search(r'(?:(?:重点|主要|着重|只)(?:讨论|介绍|解释|分析|关注)|改讲|现在(?:讨论|讲)|接下来(?:讨论|讲))\s*(.+)',clause)
        if focus:
            names=topics(focus[1])
            if len(names)==1:emphasized.extend(names)
        # "It differs from BST" is subordinate; BST is not an independent discussion subject.
        if COMPARISON.search(clause) or re.search(r'与|相比|对比|对照|比较',clause):
            continue
        names=topics(clause)
        if len(names)==1 and re.search(r'是什么|什么是|如何|为什么|呢|解释|介绍|定义|特点|原理',clause):
            subjects.extend(names)
    chosen=set(emphasized or subjects)
    if len(chosen)==1:return next(iter(chosen))
    if chosen:return None
    names=topics(question)
    return names[0] if len(names)==1 else None


def variants(query):
    return tuple(dict.fromkeys(m[1].casefold() for m in PARTITION_VARIANT.finditer(query)))


def contextual(query):
    return bool(REFERENCE.search(query) or CASE_FOLLOWUP.fullmatch(query)
                or not topics(query) and ROTATION_REFERENCE.search(query))


def history_focus(turns):
    """Replay bounded user discourse. Comparands/operations cannot seize the main topic."""
    anchor = variant = task = None
    for index, turn in enumerate(turns):
        query = turn.question
        names = topics(query)
        stated = variants(query)
        reference = contextual(query)
        independent = bool(names and not REFERENCE.match(query) and not re.search(r'(?:和|与|跟|同)它', query))
        if TOPIC_SWITCH.search(query) or independent or not reference:
            anchor = discourse_focus(query)
            variant = stated[0] if anchor == '快速排序' and len(stated) == 1 else None
            task = query if variant else None
            if len(stated) > 1:
                anchor = None  # A comparison between two partition variants has no implicit subject.
            continue
        if index == 0 and anchor is None:
            # The first definition can have fallen outside the three-turn window. Only the
            # server's saved resolution bootstraps an incomplete first turn, never model prose.
            anchor = discourse_focus(turn.resolved_query)
            saved = variants(turn.resolved_query)
            variant = saved[0] if anchor == '快速排序' and len(saved) == 1 else None
            if variant and '；用户原题条件（不作为证据）：' in turn.resolved_query:
                try:
                    conditions = json.loads(turn.resolved_query.split('；用户原题条件（不作为证据）：', 1)[1])
                    original = conditions.get('untrusted_user_task')
                    if (conditions.get('partition_variant') == variant and isinstance(original, str)
                            and variants(original) == (variant,)):
                        task = original
                except (ValueError, AttributeError):
                    pass
        if names and (len(names) != 1 or names[0] != anchor) and not COMPARISON.search(query):
            anchor = variant = task = None
        if stated:
            variant = stated[0] if anchor == '快速排序' and len(stated) == 1 else None
            task = query if variant else None
    return anchor, variant, task


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
        return {'method': 'bounded-topic-rules-v4', 'resolved_query': self.query,
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
    focused = focused_plan(query, turns, max_query_chars)
    if focused is not None:
        return focused
    explicit = topics(query)
    needs_context = contextual(query)
    # A complete named question may contain a later pronoun referring to its own subject.
    if explicit and not REFERENCE.match(query) and not re.search(r'(?:和|与|跟|同)它', query):
        needs_context = False
    if not needs_context:
        # Independent new topics do not inherit unrelated conversation content.
        relevant = tuple(t for t in turns if set(topics(t.resolved_query)) & set(explicit)) if explicit else ()
        return Plan(query, relevant)
    if not turns:
        return Plan(query, reason='conversation_context_required')
    if TOPIC_SWITCH.search(query) and not explicit:
        return Plan(query, reason='conversation_context_ambiguous')
    anchor, variant, task = history_focus(turns)
    if anchor is None:
        return Plan(query, reason='conversation_context_ambiguous')
    if not explicit and ROTATION_REFERENCE.search(query) and anchor != 'AVL 树':
        return Plan(query, reason='conversation_context_ambiguous')
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
    if variant and not variants(query):
        # Preserve the named variant as user conditions, not as textbook evidence. Include
        # only the original user task, never a historical assistant's partition result.
        rewritten += '；用户原题条件（不作为证据）：' + json.dumps(
            {'partition_variant': variant, 'untrusted_user_task': task}, ensure_ascii=False)
    if len(rewritten) > max_query_chars:
        raise AuthError(422, 'conversation_query_limit', 'Resolved question exceeds retrieval limit')
    return Plan(rewritten, turns)


def focused_plan(query, turns, limit):
    """Resolve concrete user inputs/numbered steps, never treat a prior solution as evidence."""
    is_code = bool(re.search(r'这个函数|该函数|这段代码', query) or MODIFICATION.search(query))
    step = STEP.search(query)
    continuation = NEXT_INSERT.fullmatch(query)
    if not (is_code or step or continuation):
        return None
    if is_code and FUNCTION.search(query):
        return Plan(query)  # A newly pasted function is explicit input, not a historical referent.
    if not turns:
        return Plan(query, reason='conversation_context_required')

    def finish(anchor, data):
        rewritten = anchor + '：' + json.dumps({**data, 'followup': query}, ensure_ascii=False)
        if len(rewritten) > limit:
            return Plan(query, reason='conversation_context_ambiguous')
        return Plan(rewritten, turns)

    if continuation:
        # Advance only a user-defined, explicitly staged sequence; no cursor inferred from model prose.
        for i in range(len(turns)-1, -1, -1):
            task = turns[i].question
            count = first_insert_count(task)
            if count is None:
                if not NEXT_INSERT.fullmatch(task):
                    break
                continue
            keys = operation_sequence(task)
            names = topics(task)
            if (len(names) != 1 or not re.search(r'初始为空|空(?:AVL|B\s*\+?|二叉(?:搜索|排序)?)?树|从空树', task, re.I)
                    or not keys or not 0 < count < len(keys)):
                break
            done = count + len(turns)-i-1
            if done >= len(keys) or any(not NEXT_INSERT.fullmatch(t.question) for t in turns[i+1:]):
                break
            return finish(names[0]+'插入', {'untrusted_user_task': task,
                'requested_prefix_count': done+1, 'next_key': keys[done],
                'instruction': '从原题初始状态重新核算此前缀，不把历史树图当作正确状态。'})
        return Plan(query, reason='conversation_context_ambiguous')

    if is_code:
        # Only complete, bounded user-supplied functions. A model-invented function is not an anchor.
        for turn in reversed(turns):
            task = turn.question
            functions = list(FUNCTION.finditer(task))
            if not functions:
                if turn is turns[-1] and not (MODIFICATION.search(task) or re.search(r'这个函数|该函数|这段代码', task)):
                    break
                continue
            if len(functions) != 1 or len(task.encode()) > 768:
                break
            name = functions[0][1] or functions[0][2]
            body = task[functions[0].end():]
            features = '递归终止条件' if re.search(r'\b'+re.escape(name)+r'\s*\(', body) or '递归' in task else '循环终止条件' if re.search(r'while|for', body) else '函数边界条件'
            return finish(features, {'untrusted_user_code': task, 'function': name,
                'instruction': '仅静态分析用户代码，用本轮教材证据核查；历史修正代码不保证正确。'})
        return Plan(query, reason='conversation_context_ambiguous')

    # Numbered model steps identify a claim to check, never establish that it actually happened.
    previous = turns[-1]
    names = topics(previous.resolved_query)
    if len(names) != 1:
        return Plan(query, reason='conversation_context_ambiguous')
    number = int(step[1]) if step[1].isdigit() else '一二三四五六七八九十'.index(step[1])+1
    candidates = []
    in_code = False
    for line in previous.answer.splitlines():
        if line.strip().startswith('```'):
            in_code = not in_code
            continue
        if in_code:
            continue
        match = re.match(r'\s*(?:\*\*)?(?:'+str(number)+r'[.)、]\s+|第'+step[1]+r'步\s*[:：])(.+)', line)
        if match:
            candidates.append(CITATION.sub('', match[1]).strip())
    if len(candidates) != 1 or len(candidates[0].encode()) > 384:
        return Plan(query, reason='conversation_context_ambiguous')
    return finish(names[0], {'untrusted_user_task': previous.question,
        'untrusted_previous_step': candidates[0], 'step_number': number,
        'instruction': '先核查历史步骤是否正确，不假定其交换或结论成立；只引用本轮证据。'})


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
