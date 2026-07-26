# Domain Docs

Engineering skills 探索 codebase 时，应如何消费 domain documentation。

## Before exploring, read these

- repo 根目录的 **`CONTEXT.md`**（如果存在）
- **`docs/adr/`** — 读取与你即将处理区域相关的 ADRs

如果这些文件不存在，**静默继续**。

## File structure

Single-context repo：

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── adr-001-grill-review.md
│   └── adr-002-cleanup-v1-residue.md
└── src/
```
