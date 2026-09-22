"""Stable output schema and review batches for WeCom messages."""

from datetime import datetime, timedelta, timezone
import hashlib
import json


TZ = timezone(timedelta(hours=8), "Asia/Shanghai")


def time_window(hours=24, start=None, end=None, now=None):
    def parse(value):
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=TZ) if parsed.tzinfo is None else parsed.astimezone(TZ)

    if start and not end:
        raise ValueError("指定起点时必须同时指定终点")
    stop = parse(end) if end else (now or datetime.now(TZ)).astimezone(TZ)
    begin = parse(start) if start else stop - timedelta(hours=hours)
    if begin >= stop:
        raise ValueError("起点必须早于终点")
    return {
        "start": begin.isoformat(),
        "end": stop.isoformat(),
        "timezone": "Asia/Shanghai (UTC+08:00)",
        "start_epoch": begin.timestamp(),
        "end_epoch": stop.timestamp(),
        "interval": "[start, end)",
    }


def stats(messages):
    senders = {
        message["sender_id"]
        for message in messages
        if message["type"] != "系统" and message["sender_mapping"] != "unresolved"
    }
    types = {}
    for message in messages:
        types[message["type"]] = types.get(message["type"], 0) + 1
    return {
        "message_count": len(messages),
        "speaker_count": len(senders),
        "types": types,
        "unresolved_sender_messages": sum(
            message["sender_mapping"] == "unresolved" for message in messages
        ),
    }


def write_messages(directory, metadata, messages):
    directory.mkdir(parents=True, exist_ok=False)
    data = {"schema_version": 1, "metadata": {**metadata, **stats(messages)}, "messages": messages}
    (directory / "messages.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        f"{metadata['group_name']} | {metadata['window']['start']} ≤ 时间 < {metadata['window']['end']}",
        "范围：本机已同步可用消息，不代表完整群历史。",
        "",
    ]
    for message in messages:
        lines.append(
            f"[{message['id']}] {message['timestamp']} {message['sender_name']} "
            f"({message['sender_id']}) [{message['type']}]\n{message['text']}"
        )
        lines.append("")
    (directory / "messages.txt").write_text("\n".join(lines), encoding="utf-8")

    batches = directory / "batches"
    batches.mkdir()
    current, size, manifest = [], 0, []

    def save():
        if not current:
            return
        name = f"batch-{len(manifest) + 1:04d}.json"
        text = json.dumps(current, ensure_ascii=False, indent=2)
        path = batches / name
        path.write_text(text, encoding="utf-8")
        manifest.append(
            {
                "file": name,
                "message_ids": [message["id"] for message in current],
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )

    for message in messages:
        compact = {
            key: message[key]
            for key in ("id", "timestamp", "sender_name", "type", "text", "quote", "warnings")
        }
        length = len(json.dumps(compact, ensure_ascii=False))
        if current and size + length > 12000:
            save()
            current, size = [], 0
        current.append(compact)
        size += length
    save()
    (batches / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return data
