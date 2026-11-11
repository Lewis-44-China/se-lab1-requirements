#!/usr/bin/env python3
"""按实验三手册 3.2 的提交结构生成 zip。

包内结构（只在手册要求范围内）：
    实验3_241220022_邓景文/
    ├── 实验报告.pdf
    ├── UML/（11 对 PNG/PUML）
    └── code/（可运行的 Python 包、测试、schema、Makefile）

自己的素材（报告素材、进度记录、AI 使用记录、需求对照、README 等）不打包。

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
            "缺少 lab3/报告/实验报告.pdf；请先运行 报告/导出PDF.sh，"
            "或使用 --skip-report 做结构检查。"
        )

    # 手册示例只要求 UML 的 png/puml，说明文档属于我们自己的素材，不打包。
    for path in sorted((LAB3 / "UML").iterdir()):
        if path.suffix.lower() in (".png", ".puml"):
            copy_file(path, STAGE / "UML" / path.name)

    code_src = LAB3 / "code"
    for name in ("schema.sql", "main.py", "Makefile", "pylintrc", "README.md"):
        copy_file(code_src / name, STAGE / "code" / name)
    copy_tree(code_src / "ticketing", STAGE / "code" / "ticketing", (".py",))
    copy_tree(code_src / "tests", STAGE / "code" / "tests", (".py",))


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
    """检查手册要求的必备项、数量和禁止项。"""
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        names = [item.filename for item in infos]
        print("条目数：", len(infos))
        print("压缩包大小：%.2f MB" % (zip_path.stat().st_size / 1024 / 1024))
        print("sha256：", hashlib.sha256(zip_path.read_bytes()).hexdigest())
        print("puml：", sum(name.endswith(".puml") for name in names))
        print("UML png：", sum(name.endswith(".png") and "/UML/" in name for name in names))
        print("code py：", sum(name.endswith(".py") and "/code/" in name for name in names))

        bad_flag = [
            item.filename
            for item in infos
            if any(ord(ch) > 127 for ch in item.filename)
            and not (item.flag_bits & 0x800)
        ]
        print("非 ASCII 文件名未设置 UTF-8 标志：", bad_flag or "无")

        forbidden = (
            ".pyc",
            "__pycache__",
            "ticketing.db",
            "/exports/",
            ".pylint.d",
            "AI使用记录",
            "需求与设计实现对照",
            "README.txt",
            "报告素材",
            "杂物",
        )
        bad = [name for name in names if any(key in name for key in forbidden)]
        print("禁止项：", bad or "无")

        if not skip_report:
            assert any(name.endswith("实验报告.pdf") for name in names), "缺少报告 PDF"
        assert sum(name.endswith(".puml") for name in names) == 11, "puml 数量不对"
        assert (
            sum(name.endswith(".png") and "/UML/" in name for name in names) == 11
        ), "UML png 数量不对"
        assert any(name.endswith("/code/main.py") for name in names), "缺少 code/main.py"
        assert not bad, "存在禁止文件"
        assert not bad_flag, "存在未设置 UTF-8 标志的中文文件名"


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
