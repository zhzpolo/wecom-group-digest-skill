import argparse
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sys

from .messages import time_window


def main():
    parser = argparse.ArgumentParser(
        description="本人本地企业微信群导出；当前智能体读完批次后撰写并渲染总结。"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="只检查环境，不读取聊天正文或进程内存")

    demo = commands.add_parser("demo", help="生成明确标注的虚构测试报告")
    demo.add_argument("--output", default="outputs")

    export = commands.add_parser("export", help="捕获内存密钥并只读导出指定群")
    export.add_argument("--group", required=True, help="完整群名，不接受模糊匹配")
    export.add_argument("--data-dir")
    export.add_argument("--hours", type=int, choices=[24, 48, 72], default=24)
    export.add_argument("--start")
    export.add_argument("--end")
    export.add_argument("--output", default="outputs")
    export.add_argument("--capture-seconds", type=int, default=45)
    export.add_argument("--snapshot-attempts", type=int, default=8)
    export.add_argument("--exit-fallback", action="store_true")
    export.add_argument("--exit-wait-seconds", type=int, default=600)
    export.add_argument("--confirm-process-attach", action="store_true")

    report = commands.add_parser("render", help="校验 report.json 并生成 HTML/Markdown/PNG")
    report.add_argument("directory", type=Path)

    batch = commands.add_parser("batch", help="输出一个批次供智能体完整阅读")
    batch.add_argument("directory", type=Path)
    batch.add_argument("number", type=int)
    args = parser.parse_args()

    if args.command == "doctor":
        from .windows import data_directories, processes

        packages = {}
        for name in ("pycryptodome", "psutil", "frida", "playwright", "pillow", "pytest"):
            try:
                packages[name] = version(name)
            except Exception:
                packages[name] = None
        print(
            json.dumps(
                {
                    "os": platform.platform(),
                    "python": sys.version,
                    "data_directories": [str(path) for path in data_directories()],
                    "processes": processes(),
                    "packages": packages,
                    "edge_found": Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe").exists(),
                    "real_read_verified": None,
                    "note": "doctor 不读取聊天正文、不附加进程，也不证明当前构建兼容。",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if args.command == "demo":
        from .demo import demo

        print(demo(args.output).resolve())
        return

    if args.command == "export":
        if not args.confirm_process_attach:
            raise ValueError("读取运行中企业微信密钥需要显式传入 --confirm-process-attach")
        from .capture import capture_key
        from .exporter import export_group
        from .snapshot import SnapshotUnstable
        from .windows import choose_data_directory, client_identity, is_running, wait_for_exit

        if not is_running():
            raise RuntimeError("请先登录并保持企业微信运行；密钥不会从磁盘读取或缓存")
        window = time_window(args.hours, args.start, args.end)
        print(
            f"固定时间范围：{window['start']} ≤ 时间 < {window['end']} {window['timezone']}",
            flush=True,
        )
        data_dir = choose_data_directory(args.data_dir)
        client = client_identity()
        key = None
        try:
            key, capture_info = capture_key(data_dir / "message.db", args.capture_seconds)
            try:
                directory, data = export_group(
                    data_dir,
                    key,
                    args.group,
                    window,
                    args.output,
                    client,
                    attempts=args.snapshot_attempts,
                    snapshot_mode="online",
                    capture_info=capture_info,
                )
            except SnapshotUnstable:
                if not args.exit_fallback:
                    raise RuntimeError(
                        "在线快照持续变化；如用户同意临时退出，请用 --exit-fallback 重新运行"
                    )
                print(
                    "ACTION_REQUIRED：请用户从托盘正常退出企业微信；程序不会强制关闭，密钥仅保留在当前进程内存。",
                    flush=True,
                )
                if not wait_for_exit(args.exit_wait_seconds):
                    raise RuntimeError("等待企业微信退出超时；未导出任何消息")
                directory, data = export_group(
                    data_dir,
                    key,
                    args.group,
                    window,
                    args.output,
                    client,
                    attempts=args.snapshot_attempts,
                    snapshot_mode="client_closed_fallback",
                    capture_info=capture_info,
                )
            print(
                json.dumps(
                    {
                        "output": str(directory.resolve()),
                        "group": data["metadata"]["group_name"],
                        "message_count": data["metadata"]["message_count"],
                        "speaker_count": data["metadata"]["speaker_count"],
                        "snapshot_mode": data["metadata"]["snapshot_mode"],
                    },
                    ensure_ascii=False,
                )
            )
        finally:
            if key is not None:
                key[:] = bytes(len(key))
        return

    if args.command == "render":
        from .report import render, screenshot

        render(args.directory)
        print(json.dumps(screenshot(args.directory), ensure_ascii=False, indent=2))
        return

    if args.command == "batch":
        path = args.directory / "batches" / f"batch-{args.number:04d}.json"
        print(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, PermissionError, FileNotFoundError) as error:
        print("未完成：" + str(error), file=sys.stderr)
        raise SystemExit(2)
