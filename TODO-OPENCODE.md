# Opencode 集成问题追踪

## 现状

### 问题描述

QoderClaw 与 Opencode 集成时，**工作目录 (cwd) 获取不准确**。当用户在 Opencode 中切换项目时，QoderClaw 无法正确识别当前项目的实际路径。

### 根本原因

通过 Playwright 测试发现，Opencode 的 Session API 存在设计缺陷：

1. **Session.directory 字段不准确**
   - 返回的是 Opencode 启动目录（如 `/home/user/workspace`）
   - 不随项目切换而更新

2. **Session.projectID 字段固定为 `"global"`**
   - 即使切换子项目，projectID 不变
   - 无法关联到具体的项目路径

3. **真实的项目路径在其他 API**
   - `/project` API 返回所有项目列表，包含 `worktree` 字段
   - 但无法确定哪个是"当前活跃"项目

### 测试数据

```bash
# Session API 返回
curl http://127.0.0.1:3000/session/ses_xxx
{
  "id": "ses_2c1ae26e2ffe13V7uGE759HGzd",
  "projectID": "global",
  "directory": "/home/user/workspace",  // ❌ 只是启动目录
  ...
}

# Project API 返回
curl http://127.0.0.1:3000/project
[
  {
    "id": "50f91094249554937fb198b5738f4576538122e2",
    "worktree": "/home/user/workspace/project-a"  // ✅ 真实项目路径
  },
  {
    "id": "f3fe97f01d6394193a05faf4493a37985e650172",
    "worktree": "/home/user/workspace/project-b"
  }
]
```

### 当前 QoderClaw 的临时方案

在 `openai_compat.py` 中实现了以下逻辑：

1. 按 `time.updated` 排序找最近活跃的 session
2. session_key 包含目录哈希：`oc-{session_id}-{dir_hash}`
3. 不同目录会创建不同的 Qoder session

**问题**：由于 Opencode 的 `directory` 字段不准确，切换子项目时仍然返回错误的目录。

## 解决方案

### 方案 1：修改 Opencode 源码（推荐）

让 Opencode 在发送请求时，添加请求头包含真实项目路径：

```http
x-opencode-worktree: /home/user/workspace/project-a
```

**优点**：
- 最准确的方案
- 不依赖启发式猜测

**缺点**：
- 需要修改 Opencode 源码
- 需要重新编译/部署

### 方案 2：Opencode 提供新的 API 端点

添加 `/current-project` 或类似端点，返回当前活跃的项目信息：

```json
{
  "id": "50f91094249554937fb198b5738f4576538122e2",
  "worktree": "/home/user/workspace/project-a"
}
```

**优点**：
- 不需要修改请求格式
- 后端可以主动查询

**缺点**：
- 仍然需要修改 Opencode
- 可能有并发/时序问题

### 方案 3：启发式推断（临时方案）

在 QoderClaw 中根据请求内容推断项目路径：

- 分析用户消息中的文件路径
- 匹配 `/project` API 返回的项目列表
- 选择最可能的项目

**优点**：
- 不需要修改 Opencode
- 立即可用

**缺点**：
- 不可靠，可能推断错误
- 增加复杂度

### 方案 4：用户手动指定（当前做法）

用户通过 `/cd` 命令手动切换目录：

```
/cd /path/to/your/project
```

**优点**：
- 100% 准确
- 实现简单

**缺点**：
- 用户体验差
- 每次切换项目都要手动执行

## 待办事项

- [ ] 与 Opencode 团队沟通，确认 Session API 的设计意图
- [ ] 评估是否可以修改 Opencode 添加 `x-opencode-worktree` 请求头
- [ ] 如果 Opencode 无法修改，实现方案 3（启发式推断）作为 fallback
- [ ] 更新文档，说明 Opencode 集成的已知限制

## 相关代码

- `src/openai_compat.py:220-250` - 从 Opencode API 获取 cwd 的逻辑
- `test_opencode_session.py` - Playwright 测试脚本

## 参考

- Opencode Session API: `http://127.0.0.1:3000/session`
- Opencode Project API: `http://127.0.0.1:3000/project`
