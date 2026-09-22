"""Conservative UTF-8 and protobuf text extraction for WeCom message fields."""

import re


def _read_varint(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while position < len(data) and shift < 64:
        byte = data[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, position
        shift += 7
    raise ValueError("invalid protobuf varint")


def _clean_text(value: str) -> str:
    value = "".join(
        character if character in "\n\t" or character.isprintable() else " "
        for character in value
    )
    value = re.sub(r"[ \t]+", " ", value)
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def _protobuf_text(data: bytes, depth: int = 0) -> list[str]:
    if depth > 4 or not data:
        return []
    position = 0
    values: list[str] = []
    try:
        while position < len(data):
            tag, position = _read_varint(data, position)
            wire_type = tag & 7
            if tag == 0:
                return []
            if wire_type == 0:
                _, position = _read_varint(data, position)
            elif wire_type == 1:
                position += 8
            elif wire_type == 5:
                position += 4
            elif wire_type == 2:
                length, position = _read_varint(data, position)
                if position + length > len(data):
                    return []
                segment = data[position : position + length]
                position += length
                try:
                    text = _clean_text(segment.decode("utf-8")) if b"\x00" not in segment else ""
                except UnicodeDecodeError:
                    text = ""
                if len(text) >= 2 and not re.fullmatch(r"[0-9a-fA-F]{32,}", text):
                    values.append(text)
                else:
                    values.extend(_protobuf_text(segment, depth + 1))
            else:
                return []
            if position > len(data):
                return []
    except (ValueError, IndexError):
        return []
    return list(dict.fromkeys(value for value in values if value))


def decode_content(raw) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return _clean_text(raw)
    data = bytes(raw)
    if not data:
        return ""
    try:
        plain = data.decode("utf-8")
        controls = sum(1 for byte in data if byte < 32 and byte not in (9, 10, 13))
        if controls / len(data) <= 0.08:
            return _clean_text(plain)
    except UnicodeDecodeError:
        pass
    values = _protobuf_text(data)
    return "\n".join(values[:12]) if values else f"[二进制内容 {len(data)} 字节]"
