"""Optimistic stable encrypted DB/WAL/SHM snapshots with WAL validation."""

import hashlib
from pathlib import Path
import struct
import time


PAGE_SIZE = 4096


class SnapshotUnstable(RuntimeError):
    pass


def checksum(data, state=(0, 0), endian="<"):
    if len(data) % 8:
        raise ValueError("WAL 校验输入长度错误")
    first, second = state
    for left, right in struct.iter_unpack(endian + "II", data):
        first = (first + left + second) & 0xFFFFFFFF
        second = (second + right + first) & 0xFFFFFFFF
    return first, second


def wal_index(data):
    metadata = {
        "wal_bytes": len(data),
        "valid_frames": 0,
        "committed_frames": 0,
        "tail_reason": None,
    }
    if not data:
        return {}, None, metadata
    if len(data) < 32:
        raise ValueError("WAL 头不完整，需重新获取快照")
    magic, version, page_size = struct.unpack(">III", data[:12])
    if magic not in (0x377F0682, 0x377F0683) or version != 3007000 or page_size != PAGE_SIZE:
        raise ValueError("不支持的 WAL 格式")
    endian = "<" if magic == 0x377F0682 else ">"
    state = checksum(data[:24], endian=endian)
    if state != struct.unpack(">II", data[24:32]):
        raise ValueError("WAL 头校验失败")
    pending, committed, final_size = {}, {}, None
    step = 24 + PAGE_SIZE
    for offset in range(32, len(data), step):
        frame = data[offset : offset + step]
        if len(frame) != step:
            metadata["tail_reason"] = "incomplete_tail"
            break
        page_number, commit_size = struct.unpack(">II", frame[:8])
        if frame[8:16] != data[16:24]:
            metadata["tail_reason"] = "stale_salt_tail"
            break
        expected = checksum(frame[:8] + frame[24:], state, endian)
        if expected != struct.unpack(">II", frame[16:24]) or not page_number:
            metadata["tail_reason"] = "invalid_checksum_tail"
            break
        state = expected
        metadata["valid_frames"] += 1
        pending[page_number] = offset + 24
        if commit_size:
            committed.update(pending)
            pending.clear()
            final_size = commit_size
            committed = {page: position for page, position in committed.items() if page <= final_size}
            metadata["committed_frames"] = metadata["valid_frames"]
    metadata["uncommitted_frames"] = (
        metadata["valid_frames"] - metadata["committed_frames"]
    )
    return committed, final_size, metadata


def _read(path, limit=None):
    try:
        with path.open("rb", buffering=0) as stream:
            return stream.read() if limit is None else stream.read(limit)
    except FileNotFoundError:
        return b""


def _stamp(paths):
    result = []
    for path in paths:
        try:
            stat = path.stat()
            result.append((stat.st_ino, stat.st_size, stat.st_mtime_ns))
        except FileNotFoundError:
            result.append(None)
    return result


def snapshots(paths, attempts=8):
    """Return stable encrypted bytes; never silently accepts a torn snapshot."""
    files = [path for database in paths for path in (database, Path(str(database) + "-wal"))]
    shms = [Path(str(database) + "-shm") for database in paths]
    for attempt in range(attempts):
        try:
            before = _stamp(files)
            shm_before = [_read(path, 96) for path in shms]
            first = [_read(path) for path in files]
            equal = all(
                hashlib.sha256(_read(path)).digest() == hashlib.sha256(data).digest()
                for path, data in zip(files, first)
            )
            stable = (
                equal
                and before == _stamp(files)
                and shm_before == [_read(path, 96) for path in shms]
            )
        except PermissionError:
            time.sleep(0.25)
            continue
        if stable:
            result = {}
            for index, database in enumerate(paths):
                base, wal = first[2 * index : 2 * index + 2]
                if not base or len(base) % PAGE_SIZE:
                    raise ValueError("数据库大小不符合已验证页格式：" + database.name)
                overlay, size, info = wal_index(wal)
                shm = shm_before[index]
                if len(shm) == 96:
                    if shm[:48] != shm[48:96]:
                        break
                    if shm[12] == 1:
                        maximum_frame = struct.unpack("<I", shm[16:20])[0]
                        if maximum_frame and (
                            len(wal) < 32
                            or shm[32:40] != wal[16:24]
                            or maximum_frame != info["committed_frames"]
                        ):
                            break
                info.update(
                    {
                        "database": database.name,
                        "snapshot_method": "double_read_sha256_stat_shm",
                        "database_sha256": hashlib.sha256(base).hexdigest(),
                        "wal_sha256": hashlib.sha256(wal).hexdigest(),
                        "attempt": attempt + 1,
                    }
                )
                result[database] = (base, wal, overlay, size, info)
            else:
                return result
        time.sleep(0.15)
    raise SnapshotUnstable("企业微信数据库持续变化，未取得通过一致性检查的快照")
