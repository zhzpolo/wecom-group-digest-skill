import os
import struct

import pytest

from wecom_digest.exporter import verified_wal_prefix
from wecom_digest.snapshot import PAGE_SIZE, checksum, wal_index
from wecom_digest.wecom_crypto import (
    SQLITE_HEADER,
    database_format,
    decrypt_database_bytes,
    decrypt_page,
    encrypt_page_for_test,
    verify_key,
)


def make_wal(frames):
    header = struct.pack(">IIII", 0x377F0682, 3007000, PAGE_SIZE, 0) + os.urandom(8)
    state = checksum(header)
    result = header + struct.pack(">II", *state)
    for number, size, data in frames:
        prefix = struct.pack(">II", number, size)
        state = checksum(prefix + data, state)
        result += prefix + header[16:24] + struct.pack(">II", *state) + data
    return result


def page_one():
    page = bytearray(PAGE_SIZE)
    page[:16] = SQLITE_HEADER
    page[16:18] = PAGE_SIZE.to_bytes(2, "big")
    page[21:24] = b"\x40\x20\x20"
    page[100] = 0x0D
    page[108:124] = b"fictional-record"
    return page


def test_wecom_page_round_trip_and_key_validation():
    key = bytes.fromhex("00112233445566778899aabbccddeeff")
    encrypted = encrypt_page_for_test(key, bytes(page_one()), 1)
    assert database_format(encrypted) == "wecom-wxsqlite3-aes128"
    assert verify_key(key, encrypted)
    assert not verify_key(bytes(16), encrypted)
    assert decrypt_page(key, encrypted, 1) == bytes(page_one())


def test_only_checksum_verified_committed_wal_prefix_is_applied():
    key = bytes.fromhex("00112233445566778899aabbccddeeff")
    base_second = bytes([3]) * PAGE_SIZE
    updated_second = bytes([9]) * PAGE_SIZE
    encrypted_database = (
        encrypt_page_for_test(key, bytes(page_one()), 1)
        + encrypt_page_for_test(key, base_second, 2)
    )
    committed = encrypt_page_for_test(key, updated_second, 2)
    uncommitted = encrypt_page_for_test(key, bytes([7]) * PAGE_SIZE, 2)
    wal = make_wal([(2, 2, committed), (2, 0, uncommitted)])
    _overlay, _size, metadata = wal_index(wal)
    prefix = verified_wal_prefix(wal, metadata)
    plaintext, details = decrypt_database_bytes(encrypted_database, key, wal_bytes=prefix)
    try:
        assert metadata["valid_frames"] == 2
        assert metadata["committed_frames"] == 1
        assert details["wal_frames_applied"] == 1
        assert bytes(plaintext) == bytes(page_one()) + updated_second
    finally:
        plaintext[:] = bytes(len(plaintext))


def test_wal_checksum_failure_stops_before_bad_frame():
    wal = bytearray(make_wal([(2, 2, bytes(PAGE_SIZE)), (3, 3, bytes(PAGE_SIZE))]))
    wal[-10] ^= 1
    overlay, size, metadata = wal_index(wal)
    assert size == 2
    assert set(overlay) == {2}
    assert metadata["tail_reason"] == "invalid_checksum_tail"


def test_impossible_wal_boundary_is_rejected():
    with pytest.raises(RuntimeError, match="超出稳定快照边界"):
        verified_wal_prefix(bytes(32), {"committed_frames": 1})
