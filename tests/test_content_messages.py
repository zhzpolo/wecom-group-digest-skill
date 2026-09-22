import json

import pytest

from wecom_digest.content import decode_content
from wecom_digest.messages import time_window, write_messages


def test_content_plain_and_protobuf_text():
    assert decode_content(" 企业微信测试 ") == "企业微信测试"
    text = "项目进展正常".encode()
    assert decode_content(bytes([0x0A, len(text)]) + text) == "项目进展正常"
    assert decode_content(bytes([0xFF, 0x00])).startswith("[二进制内容")


def test_exact_half_open_window():
    window = time_window(
        start="2026-09-20T10:00:00+08:00", end="2026-09-22T10:00:00+08:00"
    )
    assert window["end_epoch"] - window["start_epoch"] == 48 * 3600
    assert window["interval"] == "[start, end)"
    with pytest.raises(ValueError):
        time_window(start="2026-09-22T10:00:00+08:00", end="2026-09-22T10:00:00+08:00")


def test_batches_cover_all_messages(tmp_path):
    window = time_window(
        start="2026-09-20T10:00:00+08:00", end="2026-09-20T11:00:00+08:00"
    )
    messages = []
    for index in range(20):
        messages.append(
            {
                "id": f"m_{index}", "sender_id": "u_1", "sender_name": "甲",
                "sender_mapping": "fictional", "timestamp": window["start"],
                "timestamp_epoch": window["start_epoch"], "type": "文本",
                "text": "虚构测试" * 200, "quote": None, "warnings": [],
            }
        )
    output = tmp_path / "export"
    write_messages(
        output,
        {"group_name": "虚构群", "window": window, "synthetic": True},
        messages,
    )
    manifest = json.loads((output / "batches" / "manifest.json").read_text(encoding="utf-8"))
    assert [message_id for batch in manifest for message_id in batch["message_ids"]] == [
        message["id"] for message in messages
    ]
