# 实验三工作区：软件实现与构建

本目录是软件工程实验三（软件实现与构建）的工作区，实现实验二设计的
**活动票务与报名系统**。实验一的需求、实验二的设计与 UML 均作为输入。

## 一、实现方案

| 项目 | 选择 | 理由 |
|---|---|---|
| 语言 | Python 3.10 | 业务规则多、状态机多；`dataclass`/`Enum`/`sqlite3` 能把 UML 类和规则直接落成代码，便于逐行审查和后续测试 |
| 存储 | SQLite 3（标准库 `sqlite3`） | 无外部依赖；单文件；支持事务、唯一约束和原子条件更新，可以落地“不超发、幂等、审计同事务” |
| 界面 | 终端菜单 | 手册不要求图形界面；四角色菜单足以展示权限、状态和业务流程，且便于自动化测试 |
| 规范 | pylint | 手册推荐的 Python 代码规范工具；当前 `pylint ticketing tests` 为 10.00/10 |
| 构建/运行 | Python 解释器 + Makefile | `python3 main.py` 直接运行；`make test` / `make lint` 统一入口 |

## 二、目录

```text
lab3/
├── code/
│   ├── ticketing/            # 主代码（30 个 .py，约 7070 行）
│   │   ├── presentation_表现层/     # 表现层：终端界面与渲染
│   │   │   ├── cli.py
│   │   │   └── render.py
│   │   ├── application_应用层/      # 应用层：用例编排与系统任务
│   │   │   ├── admin.py      # 审核、封禁、举报（A4）
│   │   │   ├── promotion.py  # Outbox 递补编排（D3/D4）
│   │   │   ├── scheduler.py  # 时间推动 + Outbox 消费
│   │   │   └── seed.py       # 演示数据
│   │   ├── domain_共享能力层/           # 共享能力层：领域对象与业务能力
│   │   │   ├── models.py / errors.py
│   │   │   ├── auth.py       # A0 + D6
│   │   │   ├── activities.py # D1
│   │   │   ├── tickets.py    # D2
│   │   │   ├── registrations.py / waitlist.py / refunds.py # D3/D4
│   │   │   ├── checkin.py    # D5
│   │   │   ├── queries.py    # Q1
│   │   │   └── reports.py    # A1
│   │   ├── common_横切能力/           # 横切能力
│   │   │   ├── audit.py      # M7
│   │   │   ├── permissions.py# M7
│   │   │   └── notifications.py # S1
│   │   ├── infrastructure_基础设施/   # 基础设施
│   │   │   ├── db.py         # S2
│   │   │   ├── clock.py
│   │   │   └── security.py
│   │   └── container.py      # 组合根
│   ├── tests/                # 115 个 unittest 测试（第三轮 4 个 expectedFailure）
│   ├── schema.sql            # 数据库表、约束、索引（数据层）
│   ├── main.py               # 入口
│   ├── Makefile              # run/test/lint/seed/clean
│   └── pylintrc              # 代码规范配置
├── UML/                      # 实验二 UML（11 对 PNG/PUML）+ 实现映射说明
├── 报告/                     # 报告正文与 PDF（由本人撰写）
├── 报告素材/                 # 行数、测试、运行、需求追踪等事实材料
├── AI使用记录.md             # AI 辅助实现的过程记录
└── 工具/打包.py              # 生成交付 zip
```

分层依赖：`presentation_表现层 → application_应用层 → domain_共享能力层 → common_横切能力 → infrastructure_基础设施`；
`container.py` 是唯一可同时引用所有层的组合根。

## 三、运行

```bash
cd lab3/code
python3 main.py                 # 首次启动自动建库并生成演示数据
python3 main.py --reset         # 删除数据库后重建（仅演示）
python3 main.py --no-seed       # 不使用演示数据
make test                       # 运行 115 个测试（4 个 expectedFailure）
make lint                       # pylint 检查
```

演示账号：

| 角色 | 手机号 | 密码 |
|---|---|---|
| 管理员 | 13800000000 | Admin@123 |
| 检票员 | 13900000000 | Inspect@123 |
| 组织者 | 13700000000 | Org@123 |
| 参与者 | 13600000001 ~ 13600000004 | Pass@123 |

演示数据包含：

- 已公开、售票中的活动（普通票容量 1，含候补记录）；
- 进行中的活动（1 人已检票、1 人待检票）；
- 已结束的活动（可查看统计、出席率、退票率）；
- 组织者草稿活动；
- 一条待处理举报。

## 四、实现范围

已实现：四角色账号；活动创建/发布审核/修改审核/取消审批；场次与票种；
报名购票；幂等；名额原子扣减；候补 FIFO 与自动递补；退票/强制退票/
活动取消退款；检票请求/通过/异常/重复检票；名单导出；统计；审计留痕；
站内通知；举报/封禁；时间推动。

明确未做或只做部分的：

- 真实支付、实名核验、二维码/闸机（REQ-001 明确不做）；
- 性能压测（REQ-043/044）未做正式基准；提供的是并发正确性测试；
- 审计保存期不自动删除（只追加，至少保留 6 个月；课程不做到期归档）；
- 图形界面；终端菜单是桌面程序，不涉及移动端；
- 组织者创建向导只创建一个场次；服务层和数据库支持多场次。

设计到实现的差异、模块映射和需求追踪见
`UML/实现映射说明.md` 与 `报告素材/需求实现追踪表.md`。

## 五、Git

- 仓库：沿用实验一/二的 GitHub 仓库；
- 分支：`lab3`（从 `lab2` 之后创建）；
- 实验一文件 `requirements.md`、`chat.txt` 与标签 `lab1-ai-draft`、`lab1-final` 保持不动；
- 推送前需用户确认。

## 六、关于实验报告

实验三手册明确要求：**实验报告不允许使用大模型辅助撰写**。
因此本目录只提供代码、AI 使用过程记录、测试/运行事实数据和章节清单；
`报告/实验报告.md` 的正文应由本人完成。`报告素材/` 中的内容是为写作提供
事实依据，不是可直接提交的报告正文。
