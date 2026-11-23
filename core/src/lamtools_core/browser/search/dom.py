"""轻量 DOM：把页面取回来的 HTML 片段解析成可查询的树（只用标准库）。

user:“在网页 DOM 尚未被展平为 Markdown 前完成结构化提取；保留每条结果的父子关系、
链接归属及结果类型”+
(所以这里不把 HTML 压成一段文本：卡片是节点，标题/链接/摘要是卡片的子节点，
「谁属于哪条结果」由树结构保证，而不是靠模型去猜边界)。

支持的选择器是**我们自己写死的一小撮语法**：标签、`.class`、`#id`、
`[attr]` / `[attr=value]` / `[attr*=value]` / `[attr^=value]` / `[attr$=value]`、
后代空格与子代 `>`、以及逗号分组。遇到不支持的语法直接抛错——
适配器写错了要在测试里立刻暴露，而不是静默少匹配一半。
"""

from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser

from . import text as text_tools

VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)

# 浏览器会隐式闭合的标签：不处理会让整棵树歪掉（搜索结果页大量使用 <li>/<p>）。
_AUTO_CLOSE_SAME = frozenset({"p", "li", "dt", "dd", "option", "tr", "td", "th", "thead", "tbody", "tfoot"})
_BLOCK_TAGS = frozenset(
    {
        "address", "article", "aside", "blockquote", "div", "dl", "fieldset", "figure", "footer", "form",
        "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "main", "nav", "ol", "p", "pre", "section",
        "table", "ul",
    }
)

_COMPOUND_RE = re.compile(
    r"""
    (?P<tag>[a-zA-Z][a-zA-Z0-9-]*|\*)?
    (?P<rest>(?:\.[-\w]+|\#[-\w]+|\[[^\]]+\])*)
    """,
    re.VERBOSE,
)
_PART_RE = re.compile(r"(\.[-\w]+|\#[-\w]+|\[[^\]]+\])")
_ATTR_RE = re.compile(r"^\[\s*([-\w:]+)\s*(?:([*^$~|]?=)\s*(?:\"([^\"]*)\"|'([^']*)'|([^\]]*)))?\s*\]$")


class SelectorError(ValueError):
    """选择器语法不在支持范围内（宁可报错，不静默少匹配）。"""


class Node:
    """一个元素节点。`text` 是子树可见文本（规范化后）。"""

    __slots__ = ("tag", "attrs", "children", "parent", "flow")

    def __init__(self, tag: str, attrs: dict[str, str] | None = None, parent: Node | None = None) -> None:
        self.tag = (tag or "").lower()
        self.attrs = attrs or {}
        self.children: list[Node] = []
        self.parent = parent
        # user:“标题里的高亮词不能被挪位置”+(Bing/百度用 <strong>/<em> 包住查询词，
        # 只按「自身文本 + 子元素」两堆拼会把它挪到末尾，读起来像被切词；
        # flow 按解析顺序保存「文本片段 / 子元素」，文本拼接与序列化都走它)。
        self.flow: list[object] = []

    # --- 基础 ---------------------------------------------------------

    def get(self, name: str, default: str = "") -> str:
        return self.attrs.get(name.lower(), default)

    @property
    def classes(self) -> list[str]:
        return [part for part in self.get("class").split() if part]

    @property
    def text(self) -> str:
        pieces: list[str] = []
        self._collect_text(pieces)
        return text_tools.normalize("".join(pieces))

    def _collect_text(self, sink: list[str]) -> None:
        if self.tag in {"script", "style", "template"}:
            return
        for item in self.flow:
            if isinstance(item, str):
                sink.append(item)
            else:
                item._collect_text(sink)
        # 块级元素之间要断开，否则相邻两段会粘成一个词。
        if self.tag in _BLOCK_TAGS and sink and not sink[-1].endswith(chr(10)):
            sink.append(chr(10))

    def iter_descendants(self):
        """深度优先、文档顺序。"""
        stack = list(reversed(self.children))
        while stack:
            node = stack.pop()
            yield node
            if node.children:
                stack.extend(reversed(node.children))

    def iter_elements(self):
        yield self
        yield from self.iter_descendants()

    def ancestors(self):
        node = self.parent
        while node is not None and node.tag != "#document":
            yield node
            node = node.parent

    def detach(self) -> None:
        if self.parent is not None:
            try:
                self.parent.children.remove(self)
            except ValueError:
                pass
            self.parent = None

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        bits = [self.tag]
        if self.get("id"):
            bits.append(f"#{self.get('id')}")
        for name in self.classes[:3]:
            bits.append(f".{name}")
        return f"<Node {' '.join(bits)}>"

    def to_html(self) -> str:
        """还原成 HTML 片段（测试与诊断用）。

        注意：同一节点内的文字会被合并到子元素之前（解析时只保留了文本片段，
        没有保留「文本/元素」的精确交错顺序）；内容不丢，顺序对正文阅读没有影响。
        """
        if self.tag == "#document":
            return "".join(child.to_html() for child in self.children)
        attrs = "".join(f' {name}="{escape(value, quote=True)}"' for name, value in self.attrs.items())
        if self.tag in VOID_TAGS:
            return f"<{self.tag}{attrs}>"
        inner = "".join(
            escape(item, quote=False) if isinstance(item, str) else item.to_html() for item in self.flow
        )
        return f"<{self.tag}{attrs}>{inner}</{self.tag}>"

    # --- 查询 ---------------------------------------------------------

    def select(self, selector: str) -> list[Node]:
        """等价于 `element.querySelectorAll`（只匹配子孙，不含自身）。"""
        return _select(self, selector)

    def first(self, selector: str) -> Node | None:
        found = self.select(selector)
        return found[0] if found else None

    def first_text(self, selectors: str | list[str]) -> str:
        for selector in _as_list(selectors):
            node = self.first(selector)
            if node is not None:
                value = node.text
                if value:
                    return value
        return ""

    def matches(self, selector: str) -> bool:
        """自身是否命中选择器（只接受单个复合选择器）。"""
        steps = _parse_complex(selector)
        if len(steps) != 1:
            raise SelectorError(f"matches() 只接受单个复合选择器：{selector}")
        return _match_compound(self, steps[0][1])


def _as_list(selectors: str | list[str] | tuple[str, ...]) -> list[str]:
    if isinstance(selectors, str):
        return [selectors] if selectors else []
    return [item for item in selectors if item]


def _parse_complex(selector: str) -> list[tuple[str, dict]]:
    text = (selector or "").strip()
    if not text:
        raise SelectorError("选择器为空")
    steps: list[tuple[str, dict]] = []
    combinator = " "
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char in " >+~":
            if char in "+~":
                raise SelectorError(f"不支持相邻/兄弟选择器：{selector}")
            if char == ">":
                if steps:
                    combinator = ">"
                index += 1
            else:
                if steps:
                    combinator = " "
                index += 1
            while index < length and text[index] == " ":
                index += 1
            continue
        match = _COMPOUND_RE.match(text, index)
        if not match or match.end() == index:
            raise SelectorError(f"不支持的选择器语法：{selector}（位置 {index}）")
        compound = _build_compound(match.group("tag"), match.group("rest") or "", selector)
        steps.append((combinator, compound))
        index = match.end()
        combinator = " "
    if not steps:
        raise SelectorError(f"选择器为空：{selector}")
    return steps


def _build_compound(tag: str | None, rest: str, selector: str) -> dict:
    compound: dict = {"tag": (tag or "*").lower(), "classes": [], "id": None, "attrs": []}
    position = 0
    while position < len(rest):
        part = _PART_RE.match(rest, position)
        if not part:
            raise SelectorError(f"不支持的选择器语法：{selector}")
        token = part.group(1)
        if token.startswith("."):
            compound["classes"].append(token[1:])
        elif token.startswith("#"):
            compound["id"] = token[1:]
        else:
            attr = _ATTR_RE.match(token)
            if not attr:
                raise SelectorError(f"不支持的属性选择器：{token}（{selector}）")
            name = attr.group(1).lower()
            op = attr.group(2) or ""
            value = attr.group(3) if attr.group(3) is not None else attr.group(4)
            if value is None:
                value = attr.group(5)
            compound["attrs"].append((name, op, value if value is not None else ""))
        position = part.end()
    return compound


def _match_compound(node: Node, compound: dict) -> bool:
    if compound["tag"] != "*" and node.tag != compound["tag"]:
        return False
    if compound["id"] is not None and node.get("id") != compound["id"]:
        return False
    if compound["classes"]:
        present = set(node.classes)
        for name in compound["classes"]:
            if name not in present:
                return False
    for name, op, value in compound["attrs"]:
        if name not in node.attrs:
            return False
        actual = node.attrs.get(name, "")
        if not op:
            continue
        if op == "=" and actual != value:
            return False
        if op == "*=" and value not in actual:
            return False
        if op == "^=" and not actual.startswith(value):
            return False
        if op == "$=" and not actual.endswith(value):
            return False
        if op == "~=" and value not in actual.split():
            return False
        if op == "|=" and not (actual == value or actual.startswith(value + "-")):
            return False
    return True


def _select(root: Node, selector: str) -> list[Node]:
    results: list[Node] = []
    seen: set[int] = set()
    for part in (selector or "").split(","):
        if not part.strip():
            continue
        steps = _parse_complex(part)
        current = [root]
        for position, (combinator, compound) in enumerate(steps):
            found: list[Node] = []
            if position == 0:
                for node in root.iter_descendants():
                    if _match_compound(node, compound):
                        found.append(node)
            elif combinator == ">":
                for parent in current:
                    for child in parent.children:
                        if _match_compound(child, compound):
                            found.append(child)
            else:
                for parent in current:
                    for node in parent.iter_descendants():
                        if _match_compound(node, compound):
                            found.append(node)
            current = found
            if not current:
                break
        for node in current:
            marker = id(node)
            if marker in seen:
                continue
            seen.add(marker)
            results.append(node)
    return results


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self.stack: list[Node] = [self.root]

    def handle_starttag(self, tag: str, attrs) -> None:
        name = tag.lower()
        self._auto_close(name)
        attributes = {key.lower(): (value if value is not None else "") for key, value in attrs}
        node = Node(name, attributes, self.stack[-1])
        self.stack[-1].children.append(node)
        self.stack[-1].flow.append(node)
        if name not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs) -> None:
        name = tag.lower()
        attributes = {key.lower(): (value if value is not None else "") for key, value in attrs}
        node = Node(name, attributes, self.stack[-1])
        self.stack[-1].children.append(node)
        self.stack[-1].flow.append(node)

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in VOID_TAGS:
            return
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == name:
                del self.stack[index:]
                return
        # 没有配对的结束标签：忽略（容忍坏 HTML，不因此丢掉后面的内容）。

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].flow.append(data)

    def _auto_close(self, tag: str) -> None:
        if tag in _AUTO_CLOSE_SAME and len(self.stack) > 1 and self.stack[-1].tag == tag:
            self.stack.pop()
            return
        if tag in _BLOCK_TAGS and len(self.stack) > 1 and self.stack[-1].tag == "p":
            self.stack.pop()


def parse(html: str) -> Node:
    """解析一段 HTML（片段或整页），宽容处理未闭合标签。"""
    builder = _TreeBuilder()
    try:
        builder.feed(html or "")
        builder.close()
    except Exception:  # noqa: BLE001 - 坏 HTML 不该让整次搜索失败
        pass
    return builder.root
