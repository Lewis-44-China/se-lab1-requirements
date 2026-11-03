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
make test    # 38 个 unittest
make lint    # pylint ticketing tests
make clean   # 删除数据库、缓存、导出文件
```

## 包结构

| 文件 | 职责 | 设计对应 |
|---|---|---|
| `ticketing/models.py` | 枚举与 dataclass | UML 类图 |
| `ticketing/db.py` | SQLite 连接/事务 | S2 |
| `ticketing/auth.py` | 注册登录 | A0 + D6 |
| `ticketing/activities.py` | 活动/场次/票种/审核 | D1 |
| `ticketing/tickets.py` | 名额原子占用/释放 | D2 |
| `ticketing/registrations.py` | 报名购票/幂等 | D3 |
| `ticketing/waitlist.py` | 候补 FIFO/退款 | D4 |
| `ticketing/refunds.py` | 退票/强制退票/活动取消 | D4 |
| `ticketing/promotion.py` | Outbox 递补编排 | D3/D4 |
| `ticketing/checkin.py` | 检票请求与处理 | D5 |
| `ticketing/queries.py` | 查询/名单/统计/审计范围 | Q1 |
| `ticketing/audit.py` | 审计留痕 | M7 |
| `ticketing/permissions.py` | 角色与数据范围 | M7 |
| `ticketing/notifications.py` | 站内消息 | S1 |
| `ticketing/scheduler.py` | 时间推动 + Outbox 消费 | 定时任务 |
| `ticketing/cli.py` | 四角色终端界面 | 表现层 |
| `ticketing/seed.py` | 演示数据 | — |
| `schema.sql` | 表、CHECK、唯一约束、索引 | 数据设计 |

## 关键规则

- 名额：`UPDATE ticket_type SET occupied = occupied + 1 WHERE id=? AND occupied < capacity`；
- 幂等：`registration.request_id` 唯一 + `(account_id, session_id)` 唯一；
- 候补：退票写 Outbox，`PromotionService` 取队首递补；
- 状态：活动/报名/候补/检票均为封闭枚举，终态不可再变；
- 审计：关键操作同事务写入，失败报名单独留痕；
- 权限：服务层强制校验；手机号仅本人/管理员可见。
