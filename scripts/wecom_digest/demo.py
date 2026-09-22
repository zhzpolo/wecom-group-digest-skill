"""Clearly labelled fictional output used to verify batching and rendering."""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import uuid

from .messages import TZ, time_window, write_messages
from .report import render, screenshot


def demo(root):
    group = "虚构企业项目群 <离线安全测试>"
    group_id = "wecom_fictional_demo"
    window = time_window(
        start="2026-09-19T09:00:00+08:00", end="2026-09-20T09:00:00+08:00"
    )
    samples = [
        (1, "甲", "文本", "建议下周一上午开评审会，大家觉得如何？"),
        (2, "乙", "文本", "收到，我还没有确认时间。"),
        (3, "甲", "文本", "决定先整理问题清单。乙负责，周日18:00前发到群里。"),
        (4, "乙", "文本", "问题清单已整理并发到群里。"),
        (5, "甲", "文本", "已收到问题清单，内容核对无误。"),
        (6, "丙", "图片", "[图片，未解析内容]"),
        (7, "甲", "文本", "接口是否兼容旧版，还需要验证。"),
        (8, "乙", "文本", '<script>alert("虚构注入测试")</script> 不应执行。'),
    ]
    messages = []
    for number, sender, message_type, text in samples:
        epoch = window["start_epoch"] + number * 600
        messages.append(
            {
                "id": "m_" + hashlib.sha256(f"demo:{number}".encode()).hexdigest()[:24],
                "server_id": str(number),
                "local_id": str(number),
                "group_id": group_id,
                "sender_id": "u_" + hashlib.sha256(sender.encode()).hexdigest()[:16],
                "sender_name": sender,
                "sender_mapping": "fictional",
                "timestamp": datetime.fromtimestamp(epoch, TZ).isoformat(),
                "timestamp_epoch": epoch,
                "raw_timestamp": int(epoch * 1000),
                "timestamp_unit": "milliseconds",
                "local_type": 2 if message_type == "文本" else 14,
                "raw_content": text,
                "type": message_type,
                "text": text,
                "links": [],
                "card": None,
                "quote": None,
                "warnings": [],
                "sources": [{"database": "fictional.db", "table": "messages", "local_id": str(number)}],
            }
        )
    directory = Path(root) / (
        "demo-" + datetime.now(TZ).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    )
    metadata = {
        "group_name": group,
        "group_id": group_id,
        "account_id": "fictional",
        "window": window,
        "synthetic": True,
        "created_at": datetime.now(TZ).isoformat(),
        "warnings": ["全部消息均为虚构，专用于解析、引用、排版和渲染验证。"],
        "deduplicated_count": 0,
        "raw_selected_count": len(messages),
        "shards": [],
        "plaintext_database_files_created": 0,
    }
    write_messages(directory, metadata, messages)

    def claim(text, category, numbers):
        return {
            "text": text,
            "category": category,
            "evidence": [
                {"message_id": messages[number - 1]["id"], "quote": messages[number - 1]["text"]}
                for number in numbers
            ],
        }

    report = {
        "schema_version": 1,
        "synthetic": True,
        "author": "固定虚构测试样例",
        "messages_sha256": hashlib.sha256((directory / "messages.json").read_bytes()).hexdigest(),
        "reviewed_batches": [
            item["sha256"]
            for item in json.loads((directory / "batches" / "manifest.json").read_text(encoding="utf-8"))
        ],
        "overview": claim("群内讨论评审准备；问题清单已提交并确认，会议时间与兼容性仍待确认。", "其他", [1, 2, 4, 5, 7]),
        "topics": [
            claim("甲建议开评审会；乙仅表示收到，不能视为会议已确定。", "建议", [1, 2]),
            claim("甲决定由乙整理问题清单，并给出截止时间。", "决定", [3]),
        ],
        "todos": [
            {
                **claim("补充旧版接口兼容性验证结果。", "未解决", [7]),
                "owner": "未明确",
                "deadline": "未明确",
                "status": "待验证",
            }
        ],
        "resolved": [claim("乙自述已提交问题清单，甲随后确认收到且核对无误。", "已确认", [4, 5])],
        "open_questions": [claim("评审会议时间是否最终确定？", "未解决", [1, 2])],
        "other": [claim("记录包含一张图片，未解析其内容。", "其他", [6])],
    }
    (directory / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    render(directory)
    screenshot(directory)
    return directory
