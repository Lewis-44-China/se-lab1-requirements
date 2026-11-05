-- 活动票务与报名系统数据库结构（SQLite 3）
-- 设计依据：实验二《00_设计基线.md》第 7 节与 UML 类图。
-- 金额统一用“分”存储，避免浮点误差；时间统一用本地时间字符串
-- "YYYY-MM-DD HH:MM:SS"，同一格式下可直接按字符串比较先后。
-- 2026-11-05 第二轮审查：补充表间关系、候补 FIFO 与冗余字段的一致性说明；
-- 表结构、约束和索引均未修改。

PRAGMA foreign_keys = ON;

-- 账号：单表 + role 区分四类角色（设计基线 5.5 节）
-- 账号字段符合我们实验二中的设计
-- 第二轮审查：account 的一行才是账号实体；id 是内部主键，phone 是业务唯一键
-- （登录标识），其他表统一用 account.id 做外键，不用手机号关联。
CREATE TABLE IF NOT EXISTS account (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    phone         TEXT    NOT NULL UNIQUE,      -- 登录标识，不代替主键
    password_hash TEXT    NOT NULL,
    password_salt TEXT    NOT NULL,
    name          TEXT    NOT NULL,
    role          TEXT    NOT NULL CHECK (
        role IN ('PARTICIPANT', 'ORGANIZER', 'INSPECTOR', 'ADMIN')),
    status        TEXT    NOT NULL DEFAULT 'NORMAL' CHECK (
        status IN ('NORMAL', 'BANNED')),
    created_at    TEXT    NOT NULL
);

-- 活动：聚合根，组织者创建；状态由组织者、管理员和时间共同推动
-- 与实验二略有不同，将活动时间属性细化到下面的session中，是合理的
CREATE TABLE IF NOT EXISTS activity (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    organizer_id           INTEGER NOT NULL REFERENCES account(id),
    name                   TEXT    NOT NULL,
    description            TEXT    NOT NULL,
    location               TEXT    NOT NULL,
    estimated_participants INTEGER NOT NULL CHECK (estimated_participants > 0),
    sale_start             TEXT    NOT NULL,
    sale_end               TEXT    NOT NULL,
    waitlist_deadline      TEXT    NOT NULL,        -- 第二轮审查：活动级候补截止，符合实验二
    refund_deadline        TEXT    NOT NULL,
    cover                  TEXT    NOT NULL DEFAULT '',
    tags                   TEXT    NOT NULL DEFAULT '',
    status                 TEXT    NOT NULL CHECK (
        status IN ('DRAFT', 'PENDING_REVIEW', 'PUBLISHED',
                   'ONGOING', 'ENDED', 'CANCELLED')),
    created_at             TEXT    NOT NULL
);

-- 场次：活动 1—N 场次；场次号由系统生成
-- 与实验二一致
CREATE TABLE IF NOT EXISTS activity_session (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id       INTEGER NOT NULL REFERENCES activity(id),
    session_no        TEXT    NOT NULL,
    start_time        TEXT    NOT NULL,
    end_time          TEXT    NOT NULL,
    checkin_open_time TEXT    NOT NULL,
    allow_waitlist    INTEGER NOT NULL DEFAULT 1 CHECK (allow_waitlist IN (0, 1)),  -- 第二轮审查：默认允许候补，资格还受活动级截止时间约束
    status            TEXT    NOT NULL CHECK (
        status IN ('NOT_OPEN', 'OPEN', 'FULL', 'CLOSED', 'CANCELLED', 'ENDED')),
    UNIQUE (activity_id, session_no)
);

-- 票种：场次 1—N 票种；occupied 是已占用名额
-- 与实验二一致
-- 第二轮审查：三级链路为 ticket_type.session_id → activity_session.id，
-- activity_session.activity_id → activity.id，即“票种→场次→活动”，票种表不再冗余存活动。
-- 票种独立成表是因为同一场次可有多个票种（VIP/NORMAL），各自有独立的票价、容量和占用数；
-- UNIQUE(session_id, kind) 保证每个场次每种票只有一条。

CREATE TABLE IF NOT EXISTS ticket_type (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   INTEGER NOT NULL REFERENCES activity_session(id),
    kind         TEXT    NOT NULL CHECK (kind IN ('VIP', 'NORMAL')),
    price_cents  INTEGER NOT NULL CHECK (price_cents >= 0),
    capacity     INTEGER NOT NULL CHECK (capacity > 0),
    occupied     INTEGER NOT NULL DEFAULT 0 CHECK (
        occupied >= 0 AND occupied <= capacity),
    UNIQUE (session_id, kind)
);

-- 报名记录：报名即购票；记录不可删除，只能改状态
-- 与实验二一致
CREATE TABLE IF NOT EXISTS registration (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id          INTEGER NOT NULL REFERENCES account(id),
    activity_id         INTEGER NOT NULL REFERENCES activity(id),
    session_id          INTEGER NOT NULL REFERENCES activity_session(id),
    ticket_type_id      INTEGER NOT NULL REFERENCES ticket_type(id),
    buyer_name          TEXT    NOT NULL,
    buyer_phone         TEXT    NOT NULL,
    ticket_kind         TEXT    NOT NULL CHECK (ticket_kind IN ('VIP', 'NORMAL')),
    status              TEXT    NOT NULL CHECK (
        status IN ('PURCHASED', 'CHECKED_IN', 'NORMAL_END',
                   'SELF_CANCELLED', 'NO_SHOW', 'ACTIVITY_CANCELLED')),
    payment_status      TEXT    NOT NULL CHECK (payment_status IN ('PAID', 'UNPAID')),
    payment_amount_cents INTEGER NOT NULL CHECK (payment_amount_cents >= 0),
    refund_amount_cents INTEGER,
    refund_time         TEXT,
    request_id          TEXT    NOT NULL UNIQUE,
    created_at          TEXT    NOT NULL,
    UNIQUE (account_id, session_id)
);

-- 候补队列：每个票种一条队列（票种 1—1 队列）
-- 与实验二一致
-- 第二轮审查：waitlist 只存 ticket_type_id，指向票种即可沿“票种→场次→活动”定位；
-- 它是实验二设计中的队列实体，与 ticket_type 一一对应（ticket_type_id UNIQUE）。
-- 技术上可把 ticket_type_id 直接并入 waitlist_record，但会牵动模型、查询、演示数据与
-- UML，最终审查阶段保留该结构；FIFO 顺序不依赖此表。
CREATE TABLE IF NOT EXISTS waitlist (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_type_id INTEGER NOT NULL UNIQUE REFERENCES ticket_type(id),
    created_at     TEXT    NOT NULL
);

-- 候补记录：队列 1—N 记录；递补成功时生成报名记录
-- 与实验二一致
-- 第二轮审查：activity_id、session_id 是反范式快照，本可由
-- waitlist_id → ticket_type.session_id → activity_session.activity_id 推出；
-- 保留是因为候补过期扫描（expire_due）和“我的候补”查询直接 join 这两列。
-- 一致性前提：系统没有“票种换场次/场次换活动”的写入口，两列只在入队时写入一次。
-- FIFO 顺序：按 join_time（秒级）升序，id 作为同秒并列的兜底；
-- 取队首见 WaitlistService.head()，由 ix_waitlist_fifo 覆盖过滤与排序。
CREATE TABLE IF NOT EXISTS waitlist_record (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    waitlist_id         INTEGER NOT NULL REFERENCES waitlist(id),
    account_id          INTEGER NOT NULL REFERENCES account(id),
    activity_id         INTEGER NOT NULL REFERENCES activity(id),
    session_id          INTEGER NOT NULL REFERENCES activity_session(id),
    join_time           TEXT    NOT NULL,
    payment_status      TEXT    NOT NULL CHECK (payment_status IN ('PAID', 'UNPAID')),
    payment_amount_cents INTEGER NOT NULL CHECK (payment_amount_cents >= 0),
    status              TEXT    NOT NULL CHECK (
        status IN ('WAITING', 'PROMOTED', 'SELF_CANCELLED', 'FAILED')),
    refund_amount_cents INTEGER,
    refund_time         TEXT,
    request_id          TEXT    NOT NULL UNIQUE,
    created_at          TEXT    NOT NULL
);

-- 同一账号同一场次同时只允许一条“候补中”记录（设计确认 C2/Q6）
CREATE UNIQUE INDEX IF NOT EXISTS ux_waitlist_active
    ON waitlist_record(account_id, session_id)
    WHERE status = 'WAITING';

-- 检票请求：报名 1—N 请求；检票员只处理请求，不直接改报名状态
-- 与实验二一致
CREATE TABLE IF NOT EXISTS check_request (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    registration_id INTEGER NOT NULL REFERENCES registration(id),
    request_no      TEXT    NOT NULL UNIQUE,
    inspector_id    INTEGER REFERENCES account(id),
    status          TEXT    NOT NULL CHECK (
        status IN ('PENDING', 'PASSED', 'ABNORMAL')),
    created_at      TEXT    NOT NULL,
    processed_at    TEXT
);

-- 审核申请：发布、修改、取消三类（第二轮审查：均由组织者发起、管理员处理）
-- 与实验二一致
CREATE TABLE IF NOT EXISTS review_application (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id   INTEGER NOT NULL REFERENCES activity(id),
    type          TEXT    NOT NULL CHECK (type IN ('PUBLISH', 'MODIFY', 'CANCEL')),
    payload       TEXT    NOT NULL DEFAULT '{}',
    status        TEXT    NOT NULL CHECK (
        status IN ('PENDING', 'APPROVED', 'REJECTED')),
    submitted_at  TEXT    NOT NULL,
    reviewer_id   INTEGER REFERENCES account(id),
    comment       TEXT    NOT NULL DEFAULT '',
    reviewed_at   TEXT
);

-- 举报：管理员处理，可联动取消活动或封禁账号
-- 与实验二一致
CREATE TABLE IF NOT EXISTS report (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_id INTEGER NOT NULL REFERENCES account(id),
    activity_id INTEGER NOT NULL REFERENCES activity(id),
    reason      TEXT    NOT NULL,
    status      TEXT    NOT NULL CHECK (
        status IN ('PENDING', 'RESOLVED', 'DISMISSED')),
    handler_id  INTEGER REFERENCES account(id),
    result      TEXT    NOT NULL DEFAULT '',
    handled_at  TEXT,
    created_at  TEXT    NOT NULL
);

-- 站内消息：S1 通知；通知本身不写审计
CREATE TABLE IF NOT EXISTS notification (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient_id INTEGER NOT NULL REFERENCES account(id),
    type         TEXT    NOT NULL CHECK (
        type IN ('REVIEW_RESULT', 'ACTIVITY_CHANGED', 'WAITLIST_PROMOTED',
                 'FORCE_REFUND', 'ACTIVITY_CANCELLED', 'WAITLIST_FAILED')),
    content      TEXT    NOT NULL,
    is_read      INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1)),
    created_at   TEXT    NOT NULL
);

-- 审计留痕：只追加，不更新、不删除；关键操作与业务同事务写入
-- 与实验二一致
CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    operator_id   INTEGER REFERENCES account(id),
    operated_at   TEXT    NOT NULL,
    object_type   TEXT    NOT NULL,
    object_id     INTEGER NOT NULL,
    action        TEXT    NOT NULL,
    before_status TEXT,
    after_status  TEXT,
    description   TEXT    NOT NULL
);

-- Outbox：退票释放名额后写事件，由递补编排器消费
-- 第二轮审查：payload 只存 ticket_type_id 与 registration_id（最小定位信息），
-- 消费时由票种反查场次、活动（promotion.py），避免重复存储同一事实。
CREATE TABLE IF NOT EXISTS outbox_message (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type   TEXT    NOT NULL,
    payload      TEXT    NOT NULL,
    status       TEXT    NOT NULL DEFAULT 'NEW' CHECK (status IN ('NEW', 'PROCESSED')),
    retry_count  INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL,
    processed_at TEXT
);

-- 检票员负责的活动（管理员分配）
CREATE TABLE IF NOT EXISTS activity_inspector (
    inspector_id INTEGER NOT NULL REFERENCES account(id),
    activity_id  INTEGER NOT NULL REFERENCES activity(id),
    assigned_at  TEXT    NOT NULL,
    PRIMARY KEY (inspector_id, activity_id)
);

-- 查询与统计常用索引
CREATE INDEX IF NOT EXISTS ix_registration_session_status
    ON registration(session_id, status);
CREATE INDEX IF NOT EXISTS ix_registration_account
    ON registration(account_id, created_at);
CREATE INDEX IF NOT EXISTS ix_waitlist_fifo
    ON waitlist_record(waitlist_id, status, join_time, id);
CREATE INDEX IF NOT EXISTS ix_audit_object
    ON audit_log(object_type, object_id, operated_at);
CREATE INDEX IF NOT EXISTS ix_audit_operator
    ON audit_log(operator_id, operated_at);
CREATE INDEX IF NOT EXISTS ix_notification_recipient
    ON notification(recipient_id, is_read, created_at);
CREATE INDEX IF NOT EXISTS ix_outbox_status
    ON outbox_message(status, id);
CREATE INDEX IF NOT EXISTS ix_review_status
    ON review_application(status, submitted_at);
