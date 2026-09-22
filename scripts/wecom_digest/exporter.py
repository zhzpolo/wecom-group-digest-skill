"""Strict read-only export for one exact local WeCom group and time window."""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import uuid

from .content import decode_content
from .messages import TZ, write_messages
from .snapshot import PAGE_SIZE, snapshots
from .wecom_crypto import database_format, decrypt_database_bytes, verify_key


MESSAGE_TABLES = ("message_table", "message_small_table", "kf_message_tableV1")
TYPE_NAMES = {
    0: "文本/混合",
    2: "文本",
    4: "图片",
    7: "语音",
    13: "链接/卡片",
    14: "图片",
    15: "图片/文件",
    38: "应用消息",
    40: "通话/音视频",
    503: "状态",
    1011: "互动/状态",
}
PLACEHOLDERS = {
    4: "[图片，未解析内容]",
    7: "[语音，未解析内容]",
    14: "[图片，未解析内容]",
    15: "[图片/文件，未解析内容]",
    40: "[通话/音视频，未解析内容]",
    1011: "[互动/状态，未解析内容]",
}


def verified_wal_prefix(wal, snapshot):
    committed_frames = int(snapshot.get("committed_frames", 0))
    if not wal or not committed_frames:
        return None
    end = 32 + committed_frames * (24 + PAGE_SIZE)
    if len(wal) < end:
        raise RuntimeError("WAL 已提交帧超出稳定快照边界")
    return wal[:end]


def open_database(path, key, captured):
    encrypted, wal, _overlay, _size, snapshot = captured
    if database_format(encrypted[:PAGE_SIZE]) != "wecom-wxsqlite3-aes128":
        raise RuntimeError(f"不支持的数据库格式: {path.name}")
    if not verify_key(bytes(key), encrypted[:PAGE_SIZE]):
        raise RuntimeError(f"密钥无法验证数据库第一页: {path.name}")
    wal_prefix = verified_wal_prefix(wal, snapshot)
    image, details = decrypt_database_bytes(encrypted, bytes(key), wal_bytes=wal_prefix)
    if details["wal_frames_applied"] != int(snapshot.get("committed_frames", 0)):
        image[:] = bytes(len(image))
        raise RuntimeError(f"WAL 已验证提交帧未被完整合并: {path.name}")
    image[18] = 1
    image[19] = 1
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.deserialize(image)
        integrity = [row[0] for row in connection.execute("pragma integrity_check")]
        if integrity != ["ok"]:
            raise RuntimeError(f"SQLite 完整性校验失败: {path.name}: {integrity[:3]}")
    except Exception:
        connection.close()
        image[:] = bytes(len(image))
        raise
    return connection, image, {
        **snapshot,
        **details,
        "verified_wal_prefix_bytes": len(wal_prefix or b""),
        "key_page1_verified": True,
        "integrity": "ok",
    }


def table_columns(connection, table):
    return {str(row[1]) for row in connection.execute(f'pragma table_info("{table}")')}


def exact_session(connection, group):
    wanted = group.strip()
    columns = table_columns(connection, "conversation_table")
    required = {"id", "name", "roomname_remark", "last_message_time", "last_message_id"}
    if not required <= columns:
        raise RuntimeError(f"未验证的会话表结构，缺少: {sorted(required - columns)}")
    rows = connection.execute(
        "select id,name,roomname_remark,last_message_time,last_message_id "
        "from conversation_table where trim(name)=? or trim(roomname_remark)=?",
        (wanted, wanted),
    ).fetchall()
    unique = {str(row["id"]): row for row in rows}
    if not unique:
        raise RuntimeError("找不到完整群名；不会使用模糊匹配替代")
    if len(unique) != 1:
        raise RuntimeError(f"完整群名匹配到 {len(unique)} 个稳定会话 ID，拒绝合并")
    return next(iter(unique.values()))


def load_names(session_db, user_db, conversation_id):
    names = {}
    user_columns = table_columns(user_db, "user_table")
    expected = {"id", "name", "real_name", "account", "external_corp_name"}
    if not expected <= user_columns:
        raise RuntimeError(f"未验证的用户表结构，缺少: {sorted(expected - user_columns)}")
    for row in user_db.execute(
        "select id,name,real_name,account,external_corp_name from user_table"
    ):
        try:
            user_id = int(row["id"])
        except (TypeError, ValueError):
            continue
        display = row["real_name"] or row["name"] or row["account"]
        if display:
            corporation = row["external_corp_name"] or ""
            names[user_id] = (
                f"{display} ({corporation})"
                if corporation and corporation not in display
                else str(display)
            )
    member_columns = table_columns(session_db, "conversation_user_table")
    if not {"conversation_id", "user_id", "nick_name"} <= member_columns:
        raise RuntimeError("未验证的群成员表结构")
    for row in session_db.execute(
        "select user_id,nick_name from conversation_user_table where conversation_id=?",
        (conversation_id,),
    ):
        if row["nick_name"]:
            names[int(row["user_id"])] = str(row["nick_name"])
    return names


def normalized_sender(sender_id, name):
    stable = "u_" + hashlib.sha256(str(sender_id).encode()).hexdigest()[:16]
    if name:
        return stable, name, "conversation_user_table/user_table"
    return stable, "未识别发言人", "unresolved"


def timestamp_scale(minimum, maximum):
    if minimum is None:
        return 1000

    def unit(value):
        for factor in (1, 1000, 1_000_000):
            if 946684800 <= int(value) / factor < 4102444800:
                return factor
        raise RuntimeError("无法验证企业微信消息时间戳单位")

    if unit(minimum) != unit(maximum):
        raise RuntimeError("同一企业微信消息表存在混合时间戳单位")
    return unit(minimum)


def normalize_message(row, table, group_id, names, scale):
    raw_type = int(row["content_type"] or 0)
    raw_content = decode_content(row["content"])
    if not raw_content or raw_content.startswith("[二进制内容"):
        raw_content = decode_content(row["extra_content"])
    if not raw_content or raw_content.startswith("[二进制内容"):
        raw_content = decode_content(row["local_extra_content"])
    type_name = TYPE_NAMES.get(raw_type, f"未知({raw_type})")
    text = PLACEHOLDERS.get(raw_type, raw_content or f"[{type_name}，未解析内容]")
    if raw_type == 0 and re.fullmatch(r"[A-Za-z0-9+/=]{20,}", text or ""):
        type_name, text = "互动/状态", "[互动/状态，未解析内容]"
    links = list(dict.fromkeys(re.findall(r'https?://[^\s<>"\x27]+', text)))
    sender_number = int(row["sender_id"] or 0)
    sender_id, sender_name, sender_mapping = normalized_sender(
        sender_number, names.get(sender_number)
    )
    raw_time = int(row["send_time"] or 0)
    epoch = raw_time / scale
    server_id, local_id = str(row["server_id"] or "0"), str(row["message_id"] or "0")
    unique = (
        f"{group_id}:server:{server_id}"
        if server_id not in ("0", "-1")
        else f"{group_id}:{table}:{local_id}"
    )
    return {
        "id": "m_" + hashlib.sha256(unique.encode()).hexdigest()[:24],
        "server_id": server_id,
        "local_id": local_id,
        "group_id": group_id,
        "sender_id": sender_id,
        "sender_name": sender_name,
        "sender_mapping": sender_mapping,
        "timestamp": datetime.fromtimestamp(epoch, TZ).isoformat(),
        "timestamp_epoch": epoch,
        "raw_timestamp": raw_time,
        "timestamp_unit": {1: "seconds", 1000: "milliseconds", 1_000_000: "microseconds"}[scale],
        "local_type": raw_type,
        "raw_content": raw_content,
        "type": type_name,
        "text": text,
        "links": links,
        "card": None,
        "quote": None,
        "warnings": []
        if raw_type in TYPE_NAMES
        else ["未知企业微信消息类型；仅保留通用文本提取结果"],
        "sources": [{"database": "message.db", "table": table, "local_id": local_id}],
    }


def deduplicate(messages):
    result, seen, duplicates = [], {}, 0
    for message in sorted(
        messages,
        key=lambda item: (item["timestamp_epoch"], item["local_id"], item["sources"][0]["table"]),
    ):
        previous = seen.get(message["id"])
        if previous is None:
            seen[message["id"]] = message
            result.append(message)
            continue
        comparable = ("raw_content", "sender_id", "local_type", "timestamp_epoch")
        if any(previous[key] != message[key] for key in comparable):
            raise RuntimeError(f"相同消息标识对应不同内容: {message['id']}")
        previous["sources"].extend(message["sources"])
        duplicates += 1
    return result, duplicates


def export_group(data_dir, key, group, window, output_root, client, attempts=8, snapshot_mode="online", capture_info=None):
    database_paths = [data_dir / name for name in ("message.db", "session.db", "user.db")]
    captured = snapshots(database_paths, attempts=attempts)
    connections, images, audit = [], [], []
    try:
        opened = {}
        for path in database_paths:
            connection, image, info = open_database(path, key, captured[path])
            opened[path.name] = connection
            connections.append(connection)
            images.append(image)
            audit.append(info)

        session = exact_session(opened["session.db"], group)
        conversation_id = str(session["id"])
        public_group_id = "wecom_" + hashlib.sha256(conversation_id.encode()).hexdigest()[:16]
        names = load_names(opened["session.db"], opened["user.db"], conversation_id)

        raw_messages, shard_info = [], []
        for table in MESSAGE_TABLES:
            columns = table_columns(opened["message.db"], table)
            if not columns:
                shard_info.append({"database": "message.db", "table": table, "target_table_present": False, "selected_rows": 0})
                continue
            required = {
                "message_id", "server_id", "sender_id", "conversation_id", "content_type",
                "send_time", "content", "extra_content", "local_extra_content",
            }
            if not required <= columns:
                raise RuntimeError(f"未验证的消息表结构 {table}，缺少: {sorted(required - columns)}")
            minimum, maximum = opened["message.db"].execute(
                f'select min(send_time),max(send_time) from "{table}"'
            ).fetchone()
            scale = timestamp_scale(minimum, maximum)
            fields = sorted(required)
            rows = opened["message.db"].execute(
                f'select {",".join(fields)} from "{table}" '
                "where conversation_id=? and send_time>=? and send_time<? order by send_time,message_id",
                (
                    conversation_id,
                    int(window["start_epoch"] * scale),
                    int(window["end_epoch"] * scale),
                ),
            ).fetchall()
            raw_messages.extend(
                normalize_message(row, table, public_group_id, names, scale) for row in rows
            )
            shard_info.append(
                {
                    "database": "message.db",
                    "table": table,
                    "target_table_present": True,
                    "selected_rows": len(rows),
                    "timestamp_unit_factor": scale,
                }
            )

        messages, duplicate_count = deduplicate(raw_messages)
        if any(
            not (window["start_epoch"] <= message["timestamp_epoch"] < window["end_epoch"])
            for message in messages
        ):
            raise RuntimeError("导出后发现消息越过固定时间窗")

        metadata = {
            "group_name": group.strip(),
            "group_id": public_group_id,
            "account_id": "wecom_account_" + hashlib.sha256(data_dir.parent.name.encode()).hexdigest()[:12],
            "window": window,
            "created_at": datetime.now(TZ).isoformat(),
            "synthetic": False,
            "reader": "wecom-group-digest/WXWork5-wxSQLite3-aes128-strict",
            "client_build": client,
            "snapshot_mode": snapshot_mode,
            "capture": capture_info or {},
            "deduplicated_count": duplicate_count,
            "raw_selected_count": len(raw_messages),
            "shards": shard_info,
            "snapshots": audit,
            "warnings": [
                "仅包含此账号、本机已同步的可用企业微信消息；无法仅从本地数据库证明云端或其他设备记录完整。",
                (
                    "企业微信运行期间取得稳定快照；仅合并通过 WAL 滚动校验且位于最后一次提交以内的帧。"
                    if snapshot_mode == "online"
                    else "在线快照持续不稳定后由用户退出客户端，再取得稳定快照。"
                ),
                "三个数据库分别通过连续两次读取、文件状态及 SHM/WAL 校验；不是跨数据库全局事务。",
                "企业微信二进制消息采用通用 UTF-8/Protobuf 文本提取；图片、语音、文件正文及嵌套内容未解析。",
            ],
            "plaintext_database_files_created": 0,
        }
        directory = Path(output_root) / (
            datetime.now(TZ).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        )
        data = write_messages(directory, metadata, messages)
        verification = {
            "schema_version": 1,
            "group_exact_match_count": 1,
            "window": window,
            "raw_selected_count": len(raw_messages),
            "deduplicated_count": duplicate_count,
            "message_count": len(messages),
            "all_messages_in_window": True,
            "database_integrity": {item["database"]: item["integrity"] for item in audit},
            "key_page1_verified": {item["database"]: item["key_page1_verified"] for item in audit},
            "snapshot_mode": snapshot_mode,
            "wal_frames_applied": {item["database"]: item["wal_frames_applied"] for item in audit},
            "plaintext_database_files_created": 0,
            "messages_sha256": hashlib.sha256((directory / "messages.json").read_bytes()).hexdigest(),
        }
        (directory / "verification.json").write_text(
            json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return directory, data
    finally:
        for connection in connections:
            connection.close()
        for image in images:
            image[:] = bytes(len(image))
