-- 活动票务与报名系统数据库结构（SQLite 3）
-- 设计依据：实验二《00_设计基线.md》第 7 节与 UML 类图。
-- 金额统一用“分”存储，避免浮点误差；时间统一用本地时间字符串
-- "YYYY-MM-DD HH:MM:SS"，同一格式下可直接按字符串比较先后。

PRAGMA foreign_keys = ON;

-- 账号：单表 + role 区分四类角色（设计基线 5.5 节）
CREATE TABLE IF NOT EXISTS account (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    phone         TEXT    NOT NULL UNIQUE,
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
CREATE TABLE IF NOT EXISTS activity (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    organizer_id           INTEGER NOT NULL REFERENCES account(id),
    name                   TEXT    NOT NULL,
    description            TEXT    NOT NULL,
    location               TEXT    NOT NULL,
    estimated_participants INTEGER NOT NULL CHECK (estimated_participants > 0),
    sale_start             TEXT    NOT NULL,
    sale_end               TEXT    NOT NULL,
    waitlist_deadline      TEXT    NOT NULL,
    refund_deadline        TEXT    NOT NULL,
    cover                  TEXT    NOT NULL DEFAULT '',
    tags                   TEXT    NOT NULL DEFAULT '',
    status                 TEXT    NOT NULL CHECK (
        status IN ('DRAFT', 'PENDING_REVIEW', 'PUBLISHED',
                   'ONGOING', 'ENDED', 'CANCELLED')),
    created_at             TEXT    NOT NULL
);

-- 场次：活动 1—N 场次；场次号由系统生成
CREATE TABLE IF NOT EXISTS activity_session (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id       INTEGER NOT NULL REFERENCES activity(id),
    session_no        TEXT    NOT NULL,
    start_time        TEXT    NOT NULL,
    end_time          TEXT    NOT NULL,
    checkin_open_time TEXT    NOT NULL,
    allow_waitlist    INTEGER NOT NULL DEFAULT 1 CHECK (allow_waitlist IN (0, 1)),
    status            TEXT    NOT NULL CHECK (
        status IN ('NOT_OPEN', 'OPEN', 'FULL', 'CLOSED', 'CANCELLED', 'ENDED')),
    UNIQUE (activity_id, session_no)
);

-- 票种：场次 1—N 票种；occupied 是已占用名额
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
CREATE TABLE IF NOT EXISTS waitlist (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_type_id INTEGER NOT NULL UNIQUE REFERENCES ticket_type(id),
    created_at     TEXT    NOT NULL
);

-- 候补记录：队列 1—N 记录；递补成功时生成报名记录
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

-- 审核申请：发布、修改、取消三类
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
