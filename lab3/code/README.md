# 活动票务与报名系统 · 实现代码

实验三实现：Python 3.10 + 标准库 `sqlite3` + 终端菜单。  
设计输入：实验二《00_设计基线.md》、11 对 UML 图。

## 运行

```bash
python3 main.py                 # 首次启动自动建库并生成演示数据
python3 main.py --reset         # 删除数据库后重建（仅演示）
python3 main.py --no-seed       # 不生成演示数据
python3 main.py --db /tmp/x.db  # 指定数据库文件
```

演示账号：

| 角色 | 手机号 | 密码 |
|---|---|---|
| 管理员 | 13800000000 | Admin@123 |
| 检票员 | 13900000000 | Inspect@123 |
| 组织者 | 13700000000 | Org@123 |
| 参与者 | 13600000001 ~ 13600000004 | Pass@123 |

## 测试与规范

```bash
make test    # 123 个 unittest
make lint    # pylint ticketing tests
make clean   # 删除数据库、缓存、导出文件
```

## 包结构

代码按架构层次组织，依赖方向自上而下：

```text
presentation_表现层 → application_应用层 → domain_共享能力层
                         → common_横切能力 → infrastructure_基础设施
                         ↘ container（组合根，可依赖所有层）
```

| 文件 | 职责 | 设计对应 |
|---|---|---|
| `ticketing/presentation_表现层/cli.py` | 四角色终端界面 | 表现层 |
| `ticketing/presentation_表现层/render.py` | 输入、表格、中文标签 | 表现层 |
| `ticketing/application_应用层/admin.py` | 审核、封禁、举报的跨服务编排 | A4 |
| `ticketing/application_应用层/promotion.py` | Outbox 候补递补编排 | D3/D4 |
| `ticketing/application_应用层/scheduler.py` | 时间推动 + Outbox 消费 | 定时任务 |
| `ticketing/application_应用层/seed.py` | 演示数据 | — |
| `ticketing/domain_共享能力层/models.py` | 枚举与 dataclass | UML 类图 |
| `ticketing/domain_共享能力层/errors.py` | 业务异常 | — |
| `ticketing/domain_共享能力层/auth.py` | 注册登录 | A0 + D6 |
| `ticketing/domain_共享能力层/activities.py` | 活动/场次/票种/审核 | D1 |
| `ticketing/domain_共享能力层/tickets.py` | 名额原子占用/释放 | D2 |
| `ticketing/domain_共享能力层/registrations.py` | 报名购票/幂等 | D3 |
| `ticketing/domain_共享能力层/waitlist.py` | 候补 FIFO/退款 | D4 |
| `ticketing/domain_共享能力层/refunds.py` | 退票/强制退票/活动取消 | D4 |
| `ticketing/domain_共享能力层/checkin.py` | 检票请求与处理 | D5 |
| `ticketing/domain_共享能力层/queries.py` | 查询/名单/统计/审计范围 | Q1 |
| `ticketing/domain_共享能力层/reports.py` | 举报提交与个人查询 | A1 |
| `ticketing/common_横切能力/audit.py` | 审计留痕 | M7 |
| `ticketing/common_横切能力/permissions.py` | 角色与数据范围 | M7 |
| `ticketing/common_横切能力/notifications.py` | 站内消息 | S1 |
| `ticketing/infrastructure_基础设施/db.py` | SQLite 连接/事务 | S2 |
| `ticketing/infrastructure_基础设施/clock.py` | 业务时钟与时间解析 | — |
| `ticketing/infrastructure_基础设施/security.py` | 口令、脱敏、金额工具 | — |
| `ticketing/container.py` | 组合根：装配全部服务 | — |
| `schema.sql` | 表、CHECK、唯一约束、索引 | 数据设计 |

分层约束：`presentation` 不直接写 SQL；`domain` 不依赖 `application`/`presentation`；
`common` 不依赖 `application`/`presentation`；只有 `container.py`、`cli.py`、`seed.py`
和测试可以导入 `container`；事务边界留在服务层。

## 关键规则

- 名额：`UPDATE ticket_type SET occupied = occupied + 1 WHERE id=? AND occupied < capacity`；
- 幂等：`registration.request_id` 唯一 + `(account_id, session_id)` 唯一；
- 候补：退票写 Outbox，`PromotionService` 取队首递补；
- 状态：活动/报名/候补/检票均为封闭枚举，终态不可再变；
- 审计：关键操作同事务写入，失败报名单独留痕；
- 权限：服务层强制校验；手机号仅本人/管理员可见。
