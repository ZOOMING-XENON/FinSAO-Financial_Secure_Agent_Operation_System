# Figma hand-off · Figma 交付说明

## Import · 导入
1. `figma-frames.svg`: drag into Figma → 3 editable frames (Home / Red approval / AI assistant). 拖入 Figma 即得 3 个可编辑画板。
2. Full screens · 完整页面: run `node server.mjs`, open http://localhost:5173, capture with the html.to.design plugin (Chrome extension for localhost). 用 html.to.design 插件抓取本地页面。
3. `architecture.svg`: system diagram for the deck · 系统架构图（答辩 PPT 用）。
4. `tokens.json`: colours, radius, type · 设计变量（可导入 Tokens Studio 或手动建 Variables）。

## Components · 组件
| Component · 组件 | Variants · 变体 |
|---|---|
| Button · 按钮 (pill) | Primary 黑 / Secondary 描边 / Danger 红 / Small |
| Tier pill · 风险标签 | Green 绿 / Yellow 黄 / Red 红 / Info 蓝 |
| Status pill · 状态标签 | SUCCESS / WAITING_APPROVAL / DENIED / ACTIVE / FROZEN / LOST |
| Card · 卡片 | Balance 余额 / Chart 统计 / Budget 预算 / Product 产品 |
| Approval sheet · 审批面板 | Yellow confirm 确认 / Red MFA 验证码 / Locked 锁定 |
| Chat · 对话 | User bubble / Bot bubble / DAG plan / Tool trace |
| Nav · 导航 | Desktop top pills / Mobile bottom 6 items + 更多 sheet |
| Chat bar · 聊天入口 | Idle / Typing / Voice unavailable 语音未接入 |

## Frames to build · 待建画板 (390×844)
总览 · 账户与流水 · 转账（选择收款人 / 复核 / 回执）· 预算 · 订阅 · 银行卡 · 理财（测评 / 产品比较 / 申购）· 储蓄罐（预览）· AI 助手 · 审批（黄 / 红 / 锁定）· 错误与空状态。
