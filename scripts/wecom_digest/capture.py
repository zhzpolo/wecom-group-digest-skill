"""Bounded in-memory capture of a WeCom wxSQLite3 key on Windows."""

import queue
import time

import frida

from .wecom_crypto import PAGE_SIZE, database_format, verify_key


AGENT = r"""
'use strict';
const seen = new Set();

function reportMaterial(address, source) {
  try {
    const material = new Uint8Array(address.readByteArray(24));
    if (material[20] !== 0x73 || material[21] !== 0x41 ||
        material[22] !== 0x6c || material[23] !== 0x54) return;
    const page = material[16] | (material[17] << 8) |
      (material[18] << 16) | (material[19] << 24);
    if (page < 1 || page > 10000000) return;
    let hex = '';
    for (let i = 0; i < 16; i++) hex += material[i].toString(16).padStart(2, '0');
    const token = hex + ':' + page;
    if (seen.has(token)) return;
    seen.add(token);
    send({type: 'candidate', key: hex, page: page, source: source});
  } catch (_) {}
}

function scanRange(base, size, source) {
  try {
    for (const hit of Memory.scanSync(base, size, '73 41 6c 54')) {
      const start = hit.address.sub(20);
      if (start.compare(base) >= 0) reportMaterial(start, source);
    }
  } catch (_) {}
}

function scanStack(context, source) {
  try {
    const sp = context.sp;
    const range = Process.findRangeByAddress(sp);
    if (range === null || range.protection.indexOf('r') < 0) return;
    let start = sp.sub(0x8000);
    if (start.compare(range.base) < 0) start = range.base;
    let end = sp.add(0x8000);
    const rangeEnd = range.base.add(range.size);
    if (end.compare(rangeEnd) > 0) end = rangeEnd;
    scanRange(start, end.sub(start).toUInt32(), source);
  } catch (_) {}
}

function hookAes(name) {
  const address = Module.findGlobalExportByName(name);
  if (address === null) return false;
  Interceptor.attach(address, {
    onEnter(args) {
      try {
        if (args[1].toInt32() === 128) scanStack(this.context, name + '-stack');
      } catch (_) {}
    }
  });
  send({type: 'hook', name: name});
  return true;
}

function initialScan() {
  let ranges = [];
  try { ranges = Process.enumerateRanges('rw-'); } catch (_) {}
  let scanned = 0;
  for (const range of ranges) {
    if (range.size > 64 * 1024 * 1024) continue;
    scanRange(range.base, range.size, 'initial-rw-scan');
    scanned++;
  }
  send({type: 'scan-complete', ranges: scanned});
}

let hooks = 0;
for (const name of ['AES_set_decrypt_key', 'AES_set_encrypt_key']) {
  if (hookAes(name)) hooks++;
}
initialScan();
send({type: 'ready', hooks: hooks});
"""


def capture_key(database, duration=45):
    """Return a page-1-verified mutable key and non-sensitive capture metadata."""
    with database.open("rb") as handle:
        page_one = handle.read(PAGE_SIZE)
    if database_format(page_one) != "wecom-wxsqlite3-aes128":
        raise ValueError("目标数据库不是已支持的企业微信 wxSQLite3 格式")

    device = frida.get_local_device()
    targets = [
        process
        for process in device.enumerate_processes()
        if process.name.lower() == "wxwork.exe"
    ]
    if not targets:
        raise RuntimeError("未发现运行中的 WXWork.exe；密钥只在企业微信运行时捕获")

    messages = queue.Queue()
    sessions, scripts, attached = [], [], []

    def make_handler(pid):
        def on_message(message, _data):
            payload = message.get("payload") if message.get("type") == "send" else None
            if isinstance(payload, dict):
                messages.put((pid, payload))

        return on_message

    for process in targets:
        try:
            session = device.attach(process.pid)
            script = session.create_script(AGENT)
            script.on("message", make_handler(process.pid))
            script.load()
            sessions.append(session)
            scripts.append(script)
            attached.append(process.pid)
        except Exception:
            continue
    if not sessions:
        raise RuntimeError("无法附加任何 WXWork.exe 进程")

    validated = None
    hooks, scans = set(), {}
    deadline = time.monotonic() + max(1, duration)
    try:
        while time.monotonic() < deadline and validated is None:
            try:
                pid, payload = messages.get(
                    timeout=min(0.5, max(0.01, deadline - time.monotonic()))
                )
            except queue.Empty:
                continue
            kind = payload.get("type")
            if kind == "hook":
                hooks.add((pid, str(payload.get("name"))))
            elif kind == "scan-complete":
                scans[pid] = int(payload.get("ranges", 0))
            elif kind == "candidate":
                try:
                    candidate = bytearray.fromhex(str(payload.get("key", "")))
                except ValueError:
                    continue
                if verify_key(bytes(candidate), page_one):
                    validated = candidate
                else:
                    candidate[:] = bytes(len(candidate))
    finally:
        for script in scripts:
            try:
                script.unload()
            except Exception:
                pass
        for session in sessions:
            try:
                session.detach()
            except Exception:
                pass

    if validated is None:
        raise RuntimeError("未发现能通过目标数据库第一页验证的企业微信密钥")
    return validated, {
        "attached_process_count": len(attached),
        "hook_count": len(hooks),
        "initial_scan_process_count": len(scans),
        "key_page1_verified": True,
    }
