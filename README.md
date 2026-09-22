# WeCom Group Digest Skill

面向 Codex 等智能体的本地 Skill：从本人已登录的 Windows 企业微信中，只读提取指定群、指定时间窗内的本地已同步记录，并生成带消息证据的中文摘要、离线 HTML、PNG、Markdown 和结构化 JSON。

默认优先在线稳定快照，通常不需要退出企业微信。只有数据库持续变化且用户提前允许退出降级时，程序才等待用户从托盘正常退出；不会强制关闭客户端。数据库密钥仅保留在当前进程内存，不写入磁盘。

## 安装

```powershell
git clone https://github.com/zhzpolo/wecom-group-digest-skill.git `
  "$env:USERPROFILE\.codex\skills\wecom-group-digest"
cd "$env:USERPROFILE\.codex\skills\wecom-group-digest"
.\scripts\setup.ps1
```

刷新 Codex 后可以说：

> 使用 $wecom-group-digest，总结企业微信群“完整群名”最近 48 小时的本地记录，并生成 HTML 报告。

## 能力边界

- 仅用于用户本人、当前 Windows 账号下已登录且本地同步的企业微信数据。
- 不是云端历史下载器，不能证明手机、云端或其他设备记录完整。
- 当前真实验证范围为 Windows 11 x64、企业微信 5.0.11.6018；其他构建必须重新完成密钥、页面、结构、消息和渲染验证。
- 图片、语音、视频、文件正文和嵌套内容默认不解析，只保留明确的类型占位。
- 聊天内容可能包含口令、个人信息或商业机密；原始导出不得自动上传或公开。

详细操作见 [SKILL.md](SKILL.md) 和 [references/OPERATIONS.md](references/OPERATIONS.md)。

## 开发验证

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1 doctor
.\scripts\run.ps1 demo
$env:PYTHONPATH = (Resolve-Path .\scripts)
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
```

## 许可证

Apache-2.0。第三方来源和改动说明见 [NOTICE](NOTICE)。
