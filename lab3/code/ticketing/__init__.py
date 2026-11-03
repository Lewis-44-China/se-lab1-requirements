"""活动票务与报名系统（实验三实现包）。

包内按实验二设计基线划分：
- models / db：领域对象与持久化；
- auth / activities / registrations / waitlist / refunds / checkin / admin：
  对应共享写能力 D1～D6；
- queries：对应只读查询 Q1；
- audit / permissions：对应业务约束 M7；
- notifications：对应技术支撑 S1；
- scheduler：时间推动与 Outbox 递补编排。
"""

__version__ = "1.0.0"
