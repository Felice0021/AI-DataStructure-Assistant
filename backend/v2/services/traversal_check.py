"""Check the result of compact, unique-label preorder/inorder exercises."""
from dataclasses import dataclass
import re

from backend.v2.services.answer_validation import AnswerValidationError

_LABELS = r'([A-Za-z](?:[\s、，,]*[A-Za-z]){1,31})(?![A-Za-z])'
_PREORDER = re.compile(r'(?:前序|先序)(?:遍历)?(?:序列)?\s*(?:为|是|[:：])?\s*' + _LABELS)
_INORDER = re.compile(r'中序(?:遍历)?(?:序列)?\s*(?:为|是|[:：])?\s*' + _LABELS)
_POSTORDER = re.compile(r'后序(?:遍历)?(?:序列)?\s*(?:为|是|[:：])\s*' + _LABELS)


def labels(match):
    return re.sub(r'[^A-Za-z]', '', match[1])


@dataclass(frozen=True)
class TraversalCheck:
    root: str
    root_index: int
    postorder: str

    def instruction(self):
        return (f'本题的序列经服务端交叉核算：根 {self.root} 在中序序列中的零基下标为 {self.root_index}，'
                f'后序序列为 {self.postorder}。正文写出“后序序列：{self.postorder}”并说明拆分过程。'
                '计算值来自题目输入，引用只支持教材遍历规则。以 0 为下标起点。')

    def validate(self, answer):
        plain = re.sub(r'[`*_]', '', answer)
        claimed = [labels(match) for match in _POSTORDER.finditer(plain)]
        if not claimed or any(value != self.postorder for value in claimed):
            raise AnswerValidationError('traversal_result_mismatch')
        root = re.escape(self.root)
        for clause in re.split(r'[。；;，,\n]', plain):
            if re.search(rf'(?<![A-Za-z]){root}(?![A-Za-z])', clause) and '中序' in clause:
                indices = re.findall(r'(?:下标|索引)\s*(?:为|是|[:：=])?\s*(\d+)', clause)
                if any(int(index) != self.root_index for index in indices):
                    raise AnswerValidationError('traversal_index_mismatch')


def calculate_traversal(query):
    """Run the output check only for a request for postorder."""
    if not re.search(r'(?:求|给出|写出|计算)[^。；!?！？]{0,60}后序', query):
        return None
    return reconstruction_from_traversals(query)


def reconstruction_from_traversals(query):
    """Return a check only when the question supplies two consistent sequences."""
    preorder, inorder = _PREORDER.search(query), _INORDER.search(query)
    if not preorder or not inorder:
        return None
    pre, ino = labels(preorder), labels(inorder)
    if len(set(pre)) != len(pre) or len(pre) != len(ino) or set(pre) != set(ino):
        return None

    def post(preorder, inorder):
        if len(preorder) != len(inorder) or set(preorder) != set(inorder):
            raise ValueError('inconsistent traversals')
        if not preorder:
            return ''
        root = preorder[0]
        i = inorder.index(root)
        return post(preorder[1:i+1], inorder[:i]) + post(preorder[i+1:], inorder[i+1:]) + root

    try:
        return TraversalCheck(pre[0], ino.index(pre[0]), post(pre, ino))
    except (ValueError, IndexError):
        return None
