"""Folded parallel tool calls: one index carrying several concatenated JSON objects.

user:“还有这条配置路径，最好不要直调，而是走 Sunday 本身用户能接触到的配置模式”+
Gemini 4 Hydrogen（星盘反重力线路）实测会把多个并行 functionCall 折叠进同一个
tool_call index：首片带 id/name/空参数，之后每个调用只再发一段完整 JSON 参数，
既不带 id 也不带 name。拼接结果形如 ``{"path":"a.txt"}{"path":"b.txt"}``，
按 JSON 严格解析必然失败，工具因此被拒绝执行。

这些测试锁定「折叠参数可被安全还原成 N 个独立调用」的契约：
1. 多个**完整** JSON 对象 → 拆成 N 个调用，参数各自正确、id 唯一；
2. 单个正常调用 → 行为完全不变（零回归）；
3. 截断/非法 JSON → 仍然报 arguments_parse_error，绝不猜测参数；
4. 可用 folded_tool_call_repair=false 关掉修复，回到原行为。
"""

import json

from lamtools_core.llm.helpers import merge_tool_call_deltas, resolve_tool_calls


def _accumulate(deltas):
    accumulated: dict = {}
    for delta in deltas:
        accumulated = merge_tool_call_deltas(accumulated, {"tool_calls": [delta]})
    return accumulated


FOLDED_READ_FILE_DELTAS = [
    # 首片：带 id 与函数名，参数为空
    {"index": 0, "id": "toolu_e135957e4dfdbf4e", "type": "function",
     "function": {"name": "read_file", "arguments": ""}},
    # 后续调用：只有一段完整参数，没有 id、没有 name
    {"index": 0, "function": {"arguments": '{"path":"a.txt"}'}},
    {"index": 0, "function": {"arguments": '{"path":"b.txt"}'}},
]


def test_folded_parallel_calls_split_into_separate_calls():
    calls = resolve_tool_calls(_accumulate(FOLDED_READ_FILE_DELTAS))

    assert len(calls) == 2
    assert [call.arguments for call in calls] == [{"path": "a.txt"}, {"path": "b.txt"}]
    # 上游只给了第一个调用的函数名；后续调用沿用同一函数名。
    assert [call.name for call in calls] == ["read_file", "read_file"]
    # 两个调用必须能被当成两次独立执行，因此 id 唯一且非空。
    assert calls[0].id == "toolu_e135957e4dfdbf4e"
    assert calls[1].id and calls[1].id != calls[0].id
    for call in calls:
        assert not call.metadata.get("arguments_parse_error")


def test_folded_three_objects_split():
    deltas = [
        {"index": 0, "id": "toolu_1", "type": "function",
         "function": {"name": "read_file", "arguments": ""}},
        {"index": 0, "function": {"arguments": '{"path":"a.txt"}{"path":"b.txt"}'}},
        {"index": 0, "function": {"arguments": '{"path":"c.txt"}'}},
    ]
    calls = resolve_tool_calls(_accumulate(deltas))

    assert [call.arguments["path"] for call in calls] == ["a.txt", "b.txt", "c.txt"]
    assert len({call.id for call in calls}) == 3


def test_folded_objects_with_whitespace_between_them():
    deltas = [
        {"index": 0, "id": "toolu_2", "type": "function",
         "function": {"name": "read_file", "arguments": ""}},
        {"index": 0, "function": {"arguments": '{"path":"a.txt"}\n  {"path":"b.txt"}'}},
    ]
    calls = resolve_tool_calls(_accumulate(deltas))

    assert [call.arguments["path"] for call in calls] == ["a.txt", "b.txt"]


def test_single_call_is_untouched():
    deltas = [
        {"index": 0, "id": "toolu_3", "type": "function",
         "function": {"name": "read_file", "arguments": ""}},
        {"index": 0, "function": {"arguments": '{"path":"a.txt"}'}},
    ]
    calls = resolve_tool_calls(_accumulate(deltas))

    assert len(calls) == 1
    assert calls[0].id == "toolu_3"
    assert calls[0].name == "read_file"
    assert calls[0].arguments == {"path": "a.txt"}


def test_truncated_arguments_still_report_error():
    deltas = [
        {"index": 0, "id": "toolu_4", "type": "function",
         "function": {"name": "read_file", "arguments": ""}},
        {"index": 0, "function": {"arguments": '{"path":"a.tx'}},
    ]
    calls = resolve_tool_calls(_accumulate(deltas))

    assert len(calls) == 1
    assert calls[0].metadata.get("arguments_parse_error") is True


def test_non_object_json_is_not_split():
    """两个 JSON 对象之间夹了非对象内容时不做猜测。"""
    deltas = [
        {"index": 0, "id": "toolu_5", "type": "function",
         "function": {"name": "read_file", "arguments": ""}},
        {"index": 0, "function": {"arguments": '{"path":"a.txt"}[1,2]'}},
    ]
    calls = resolve_tool_calls(_accumulate(deltas))

    assert len(calls) == 1
    assert calls[0].metadata.get("arguments_parse_error") is True


def test_repair_can_be_disabled():
    calls = resolve_tool_calls(
        _accumulate(FOLDED_READ_FILE_DELTAS),
        repair_folded_arguments=False,
    )

    assert len(calls) == 1
    assert calls[0].metadata.get("arguments_parse_error") is True


def test_folded_calls_without_id_get_distinct_synthetic_ids():
    deltas = [
        {"index": 0, "type": "function", "function": {"name": "read_file", "arguments": ""}},
        {"index": 0, "function": {"arguments": '{"path":"a.txt"}{"path":"b.txt"}'}},
    ]
    calls = resolve_tool_calls(_accumulate(deltas))

    assert len(calls) == 2
    assert all(call.id for call in calls)
    assert calls[0].id != calls[1].id


def test_folded_calls_report_repair_metadata():
    calls = resolve_tool_calls(_accumulate(FOLDED_READ_FILE_DELTAS))

    assert calls[0].metadata.get("folded_tool_arguments") == 2
    assert calls[1].metadata.get("folded_tool_arguments") == 2
    # 原始拼接串保留下来，便于排查上游缺陷。
    assert calls[0].metadata.get("raw_arguments") == '{"path":"a.txt"}{"path":"b.txt"}'
