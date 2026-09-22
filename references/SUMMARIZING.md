# 总结与证据规范

1. 读取 `messages.json` 的元数据、统计和告警，以及 `verification.json`。
2. 按 `batches/manifest.json` 顺序逐一读完全部批次；工具输出截断时继续分段，不能猜测尾部。
3. 后续消息可能否定、变更或完成前文事项；结论必须基于完整上下文。
4. 每条重要结论关联实际消息 ID 和该消息 `text` 中的连续原文摘录。不能把引用、图片标题或未解析附件当作本群正文。
5. 区分建议、群内观点、决定、收到、同意、执行完成、已确认和未解决。负责人或截止时间没有依据就写“未明确”。
6. 群内外部链接与事实主张默认未核验。只报告“群内有人表示”，不要写成独立事实。
7. 图片、语音、视频、文件或互动状态只有占位符时，不描述其内容。
8. `messages_sha256` 必须是 `messages.json` 实际字节的 SHA-256；`reviewed_batches` 按 manifest 顺序登记全部批次哈希。

`report.json` 顶层结构：

```json
{
  "schema_version": 1,
  "synthetic": false,
  "author": "当前智能体会话",
  "messages_sha256": "实际摘要",
  "reviewed_batches": ["全部批次摘要"],
  "overview": {"text": "概览", "category": "其他", "evidence": []},
  "topics": [],
  "todos": [],
  "resolved": [],
  "open_questions": [],
  "other": []
}
```

允许的 `category`：`群内观点`、`建议`、`决定`、`收到`、`同意`、`执行完成`、`已确认`、`未解决`、`其他`。`todos` 每项还必须包含非空的 `owner`、`deadline`、`status`；未知就填写“未明确”。
