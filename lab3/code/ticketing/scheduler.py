"""时间推动任务。

每次进入菜单或完成一个操作后调用 tick()，完成：
1. 活动/场次状态推进（公开 → 进行中 → 已结束）；
2. 候补截止后未递补的记录转为候补失败并退款；
3. 场次结束后：已购票 → 未检票；已检票 → 正常结束（缺席不释放名额）；
4. 消费 Outbox，触发候补递补。

课程项目不引入后台线程，避免多线程调试成本；用“每次操作前 tick”
模拟定时任务，行为与设计基线 ADR-12 一致。
"""

from __future__ import annotations

from .activities import ActivityService
from .audit import AuditService
from .clock import Clock, format_dt
from .db import Database
from .models import RegistrationStatus
from .promotion import PromotionService
from .waitlist import WaitlistService


class Scheduler:
    """时间推动与 Outbox 消费。"""

    def __init__(
        self,
        db: Database,
        clock: Clock,
        audit: AuditService,
        activities: ActivityService,
        waitlist: WaitlistService,
        promotion: PromotionService,
    ) -> None:
        self.db = db
        self.clock = clock
        self.audit = audit
        self.activities = activities
        self.waitlist = waitlist
        self.promotion = promotion

    def tick(self) -> dict[str, int]:
        """执行一轮时间任务，返回本轮处理数量。"""
        self.activities.refresh_statuses()
        expired = self.waitlist.expire_due()
        finalized = self._finalize_sessions()
        promoted = self.promotion.dispatch_pending()
        return {"expired": expired, "finalized": finalized, "promoted": promoted}

    def _finalize_sessions(self) -> int:
        """场次结束后推进报名记录终态。"""
        now = format_dt(self.clock.now())
        rows = self.db.query_all(
            """
            SELECT r.id, r.status, s.end_time
              FROM registration r
              JOIN activity_session s ON s.id = r.session_id
             WHERE r.status IN ('PURCHASED', 'CHECKED_IN')
               AND s.end_time <= ?
            """,
            (now,),
        )
        count = 0
        for row in rows:
            old_status = RegistrationStatus(row["status"])
            new_status = (
                RegistrationStatus.NO_SHOW
                if old_status is RegistrationStatus.PURCHASED
                else RegistrationStatus.NORMAL_END
            )
            with self.db.transaction() as conn:
                cursor = conn.execute(
                    """
                    UPDATE registration SET status = ?
                     WHERE id = ? AND status = ?
                    """,
                    (new_status.value, row["id"], old_status.value),
                )
                if cursor.rowcount != 1:
                    continue
                self.audit.record(
                    conn,
                    None,
                    "REGISTRATION",
                    int(row["id"]),
                    "REGISTRATION_STATUS_CHANGED",
                    "场次结束，系统推进报名记录终态",
                    old_status.value,
                    new_status.value,
                )
                count += 1
        return count
