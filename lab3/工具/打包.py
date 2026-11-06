#!/usr/bin/env python3
"""按实验三手册结构生成交付 zip。

包内结构：
    实验3_241220022_邓景文/
    ├── 实验报告.pdf
    ├── UML/（11 对 PNG/PUML + 说明）
    ├── code/（可运行的 Python 包、测试、schema、Makefile）
    ├── AI使用记录.md
    ├── 需求与设计实现对照.md
    └── README.txt

用法：
    python3 工具/打包.py                 # 正式打包（要求报告 PDF 已存在）
    python3 工具/打包.py --skip-report   # 仅检查/试打包，不要求 PDF
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LAB3 = REPO / "lab3"
DEFAULT_OUT = Path("/home/deng/软件工程实验/实验三")
NAME = "实验3_241220022_邓景文"
STAGE = Path("/tmp") / NAME

README = """实验三 软件实现与构建 提交包
学号：241220022    姓名：邓景文

目录说明
--------
实验报告.pdf
    实验三报告正文（由本人撰写并导出）。

UML/
    实验二设计的 11 对 UML 图（PNG + PlantUML 源文件）、UML 设计说明，
    以及“UML 到实现”的映射说明。

code/
    可运行实现：
    - ticketing/：主代码（Python 3.10，标准库 sqlite3）；
    - tests/：unittest 测试；
    - schema.sql：数据库表、约束、索引；
    - main.py：入口；
    - Makefile：run/test/lint/seed/clean；
    - pylintrc：代码规范配置。

AI使用记录.md
    AI 辅助代码实现的过程记录（场景、提示词要点、输出、问题、修复）。
    报告正文未使用大模型撰写。

需求与设计实现对照.md
    实验一需求、实验二设计与 UML 到实验三代码的逐项对照，
    集中记录实现逻辑与所有不完全一致之处。

运行方式
--------
    cd code
    python3 main.py        # 首次启动自动建库并生成演示数据
    make test              # 124 个测试
    make lint              # pylint

演示账号见 code/README.md。

补充说明
--------
- 实现使用 SQLite + 终端菜单，替代实验二的 MySQL + Web UI；
  差异见 UML/实现映射说明.md。
- 实验一 requirements.md、chat.txt 与标签未修改、未移动。
- 本包不含数据库文件、__pycache__、运行导出 CSV。
"""


def copy_file(src: Path, dst: Path) -> None:
    """复制单个文件，源不存在时给出明确错误。"""
    if not src.is_file():
        raise FileNotFoundError(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def copy_tree(src: Path, dst: Path, patterns: tuple[str, ...]) -> int:
    """按后缀复制目录树，跳过缓存和运行数据。"""
    count = 0
    for path in sorted(src.rglob("*")):
        if not path.is_file() or path.suffix not in patterns:
            continue
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(src)
        copy_file(path, dst / relative)
        count += 1
    return count


def build_stage(skip_report: bool) -> None:
    """组装临时目录。"""
    if STAGE.exists():
        shutil.rmtree(STAGE)
    (STAGE / "UML").mkdir(parents=True)
    (STAGE / "code").mkdir()

    report = LAB3 / "报告" / "实验报告.pdf"
    if report.is_file():
        copy_file(report, STAGE / "实验报告.pdf")
    elif not skip_report:
        raise FileNotFoundError(
            "缺少 lab3/报告/实验报告.pdf；请先由本人撰写报告并导出 PDF，"
            "或使用 --skip-report 做结构检查。"
        )

    for path in sorted((LAB3 / "UML").iterdir()):
        if path.suffix.lower() in (".png", ".puml") or path.name in (
            "UML设计说明.md",
            "实现映射说明.md",
        ):
            copy_file(path, STAGE / "UML" / path.name)

    code_src = LAB3 / "code"
    copy_file(code_src / "schema.sql", STAGE / "code" / "schema.sql")
    copy_file(code_src / "main.py", STAGE / "code" / "main.py")
    copy_file(code_src / "Makefile", STAGE / "code" / "Makefile")
    copy_file(code_src / "pylintrc", STAGE / "code" / "pylintrc")
    copy_file(code_src / "README.md", STAGE / "code" / "README.md")
    copy_tree(code_src / "ticketing", STAGE / "code" / "ticketing", (".py",))
    copy_tree(code_src / "tests", STAGE / "code" / "tests", (".py",))

    copy_file(LAB3 / "AI使用记录.md", STAGE / "AI使用记录.md")
    copy_file(
        LAB3 / "需求与设计实现对照.md",
        STAGE / "需求与设计实现对照.md",
    )
    (STAGE / "README.txt").write_text(README, encoding="utf-8-sig")


def build_zip(zip_path: Path) -> None:
    """用 zipfile 打包，文件名写 UTF-8 标志，兼容 Windows 解压。"""
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for dirpath, dirnames, filenames in os.walk(STAGE):
            dirnames.sort()
            for filename in sorted(filenames):
                full = Path(dirpath) / filename
                relative = full.relative_to(STAGE.parent).as_posix()
                info = zipfile.ZipInfo(
                    relative, date_time=time.localtime(full.stat().st_mtime)[:6]
                )
                info.create_system = 0
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                with zf.open(info, "w") as handle:
                    handle.write(full.read_bytes())


def verify(zip_path: Path, skip_report: bool) -> None:
    """检查数量、必备文件和禁止项。"""
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        names = [item.filename for item in infos]
        print("条目数：", len(infos))
        print("压缩包大小：%.2f MB" % (zip_path.stat().st_size / 1024 / 1024))
        print("sha256：", hashlib.sha256(zip_path.read_bytes()).hexdigest())
        print("puml：", sum(name.endswith(".puml") for name in names))
        print("UML png：", sum(name.endswith(".png") and "/UML/" in name for name in names))
        print("code py：", sum(name.endswith(".py") and "/code/" in name for name in names))
        forbidden = (
            ".pyc",
            "__pycache__",
            "ticketing.db",
            "/exports/",
            ".pylint.d",
        )
        bad = [name for name in names if any(key in name for key in forbidden)]
        print("禁止项：", bad or "无")
        if not skip_report:
            assert any(name.endswith("实验报告.pdf") for name in names), "缺少报告 PDF"
        assert any(
            name.endswith("需求与设计实现对照.md") for name in names
        ), "缺少需求与设计实现对照.md"
        assert sum(name.endswith(".puml") for name in names) == 11, "puml 数量不对"
        assert (
            sum(name.endswith(".png") and "/UML/" in name for name in names) == 11
        ), "UML png 数量不对"
        assert not bad, "存在禁止文件"


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="生成实验三交付 zip")
    parser.add_argument(
        "--skip-report", action="store_true", help="不要求报告 PDF，仅做结构检查"
    )
    parser.add_argument(
        "--output", default=str(DEFAULT_OUT), help="zip 输出目录"
    )
    args = parser.parse_args()
    try:
        build_stage(args.skip_report)
    except FileNotFoundError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{NAME}.zip"
    build_zip(zip_path)
    verify(zip_path, args.skip_report)
    print("输出：", zip_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
