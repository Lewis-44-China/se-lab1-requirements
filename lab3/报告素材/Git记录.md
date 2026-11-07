# Git 记录（事实材料）

> 用途：实验报告“Git 远程代码管理展示”章节的原始数据。不是报告正文。

## 1. 仓库与分支

| 项目 | 值 |
|---|---|
| 远程仓库 | `https://github.com/Lewis-44-China/se-lab1-requirements` |
| 工作分支 | `lab3` |
| 基线 | 实验二 `lab2` 最新提交 `e705ae6` |
| 实验一文件 | `requirements.md`、`chat.txt` 未修改 |
| 实验一标签 | `lab1-ai-draft`、`lab1-final` 未移动 |

## 2. lab3 提交历史（里程碑）

`lab3` 相对 `lab2` 共 73 个提交（2026-11-03 ～ 2026-11-07）。下面只列 9 个里程碑，后续缺陷修复与报告整理没有逐条展开；完整记录可用 `git log --oneline --graph refs/heads/lab3` 查看。

| 提交 | 内容 |
|---|---|
| `fdc54b3` | 添加实现基线、SQLite 表结构、领域枚举与数据对象、时钟/口令/审计/权限/通知基础模块 |
| `2e144ff` | 实现 A0-A4/D1-D6/Q1/M7/S1/S2 核心服务：活动审核、报名幂等、名额原子扣减、候补 FIFO/Outbox、退票、检票、查询统计 |
| `17e9fca` | 添加四角色终端界面、演示数据、Makefile 与运行入口 |
| `dcc7abd` | 添加 38 个自动化测试；修复封禁状态过期、候补递补票种查找、时钟注入等问题；pylint 10.00/10 |
| `f042582` | 添加 UML 交付、49 条需求追踪表、AI 使用记录、进度记录与打包工具 |
| `735be3d` | 按分层重组 `ticketing/` 为 presentation_表现层/application_应用层/domain_共享能力层/common_横切能力/infrastructure，更新绝对导入与 SCHEMA_PATH |
| `652fd8a` | 同步目录结构文档、UML 实现映射、进度记录与代码规模/测试素材 |
| `629618e` | 同步实验二修订版 UML（5 张图 + 设计说明），核对失败审计、重复候补、活动取消候补失败、分配检票等实现 |
| `31867c1` | 为活动创建补充独立候补截止输入，更新实现映射、基线、需求追踪与代码规模素材 |

完整哈希：

```text
31867c1a1a93995574399049769384f15857c431  lab3: 为活动创建补充独立候补截止输入
629618e95d345f02736b45eaabae00f38be74914  lab3: 同步实验二修订版 UML 并核对实现
652fd8aab697ee4a478f0d95da08b227e8a836c5  lab3: 同步分层结构文档与报告素材
735be3d2c7f632d71d6c539f729a99630c4e596d  lab3: 按分层重组 ticketing 包目录并更新导入
f042582568a0cecd1f77e3ff7c0a871b1a3228a1  lab3: 添加 UML 交付、需求追踪、AI 记录与打包工具
dcc7abdede29b486ee6503e3523f3d124ae814cf  lab3: 添加自动化测试并修复规范与业务问题
17e9fca63793dd995d5f9d6916413cfdb906c43e  lab3: 添加四角色终端界面、演示数据与运行入口
2e144ff9ae17b1b4ca9c4af6a56745ba12509b22  lab3: 实现认证、活动、报名、候补、退票与检票服务
fdc54b379362f7ddc445b42476a54fdfa1446b13  lab3: 添加实现基线、表结构与领域模型
e705ae67c0e1fb7886e96e3328861347c911974e  lab2: 添加交付包打包脚本并更新进度（基线）
```

## 3. 实验一保护校验

```bash
git diff lab1-final..lab3 -- requirements.md chat.txt
```

输出为空（无差异）。

标签指向：

| 标签 | 标签对象 | 指向提交 |
|---|---|---|
| `lab1-final` | `06c6684c8a6877c8a1a6403a37c7c5a316ca81bd` | `7a1472f56b359e334448907bff4ba5bceff12a8d` |
| `lab1-ai-draft` | `cc314353ea09c6b497b3ba7adc4de475fb0b0a3c` | `81c1055dab46c18cd7408451cb12baaced22f727` |

## 4. 远程状态

- 本地 `lab3` 已推送到 `github`，推送时远程与本地均指向 `2d142aa`；
- 推送命令：`git push -u github lab3`；
- 远程新增 `lab3` 分支，本地已设置上游 `github/lab3`；
- 未 force push，未改动标签；
- 远程仓库地址：`git@github.com:Lewis-44-China/se-lab1-requirements.git`。

## 5. 报告中可展示的内容

1. `git log --oneline --graph` 的截图/文本（报告正文只写阶段摘要）；
2. GitHub 仓库 `lab3` 分支页面截图；
3. `git diff lab1-final..lab3 -- requirements.md chat.txt` 为空；
4. 完整提交哈希与说明见本文件第 2 节及 `git log`。
