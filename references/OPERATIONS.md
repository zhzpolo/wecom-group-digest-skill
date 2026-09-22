# 操作说明

## 首次准备

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1 doctor
.\scripts\run.ps1 demo
$env:PYTHONPATH = (Resolve-Path .\scripts)
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
```

`doctor` 只枚举企业微信进程、核心数据库目录、客户端可执行文件摘要和依赖，不读取聊天正文，也不附加进程。

## 导出

先固定并向用户显示时间窗。保持企业微信运行：

```powershell
.\scripts\run.ps1 export `
  --group "完整群名" `
  --hours 48 `
  --confirm-process-attach
```

可以使用 `--start` 与 `--end` 传入带时区的 ISO-8601 时间。多个账号目录时，用 `--data-dir` 选择 `...\WXWork\<账号>\Data`。

程序在同一进程中：

1. 只读目标 `message.db` 第一页；
2. 限时附加本机 `WXWork.exe`，仅接受能验证该页的候选密钥；
3. 卸载所有注入脚本并分离；
4. 对 `message.db`、`session.db`、`user.db` 及 WAL/SHM 连续双读；
5. 验证 WAL header、salt、滚动 checksum、提交边界和 SHM header；
6. 在内存中解密并执行 `PRAGMA integrity_check`；
7. 精确匹配群名，筛选 `[start,end)` 消息并生成审计文件；
8. 在所有退出路径覆盖可变密钥和明文页缓冲。

## 退出降级

只有用户明确同意“在线失败时临时退出企业微信”后，才加入：

```powershell
--exit-fallback --exit-wait-seconds 600
```

如果在线快照持续不稳定，命令会输出 `ACTION_REQUIRED` 并等待用户从托盘退出。程序不会发送关闭信号，也不会杀进程；原始时间窗不会因此向后漂移。

如果没有预先启用降级，在线失败即停止并覆盖内存密钥。此时不要让用户先退出再重新运行，因为退出后无法重新捕获只存在于运行进程中的密钥。

## 总结与渲染

导出完成后，读取所有批次并撰写 `report.json`，然后：

```powershell
.\scripts\run.ps1 render ".\outputs\本次目录"
```

检查 HTML 的桌面/移动视图、至少一个展开来源、所有 PNG 分图、离线网络请求、中文字体、内容高度和统计数字。

## 停止条件

- 核心数据库缺失或账号不唯一；
- 没有完整群名精确匹配，或匹配多个稳定会话 ID；
- 密钥不能验证第一页；
- DB/WAL/SHM 不能形成稳定快照；
- WAL 校验、SQLite 完整性或结构适配失败；
- 重复消息 ID 对应不同内容；
- 输出时间越界或批次不完整。

任何一项失败都不得把零条或部分消息报告成成功。
