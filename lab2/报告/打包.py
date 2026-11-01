#!/usr/bin/env python3
"""按实验二手册结构生成交付 zip。

关键点：
- 只用 Python zipfile，不用 zip -r，避免 Windows 解压中文文件名乱码；
- 文件名写入 UTF-8 并设置 UTF-8 标志位；
- 条目 create_system 设为 0（MS-DOS），提高 Windows 自带解压的兼容性；
- 包内只放交付物和补充说明，不放源稿、脚本、杂物。
"""
from pathlib import Path
import hashlib
import os
import shutil
import time
import zipfile

REPO = Path(__file__).resolve().parents[2]      # lab2-repo
LAB2 = REPO / 'lab2'
OUT_DIR = Path('/home/deng/软件工程实验/实验二')
NAME = '实验2_241220022_邓景文'
STAGE = Path('/tmp') / NAME

README = """实验二 软件设计与建模 提交包
学号：241220022    姓名：邓景文

目录说明
--------
实验报告.pdf
    实验二报告正文（40 页，A4）。

UML/
    11 张 UML 图的 PNG 与 PlantUML 源文件（.puml），以及 UML 设计说明。

UI界面/
    9 张 Figma 导出的 UI 界面 PNG（1440×900），以及 UI 设计说明。

AI使用记录/
    AI使用记录.md：报告第 5 章对应的整理版（人工审查记录 + 代表性记录 + 反思）。
    AI使用记录_完整过程.md：42 条逐次 AI 使用记录。
    说明：报告中写作“杂物/AI使用记录_完整过程.md”，提交包内统一整理到本目录。

补充说明
--------
- 实验一的两个交付文件 requirements.md、chat.txt 未修改；
- 实验一的两个标签 lab1-ai-draft、lab1-final 未移动、未删除；
- 报告与界面中的活动、日期、票数、人数、日志条数等均为演示数据。
- 本包文件名使用 UTF-8 编码；如 Windows 自带解压出现乱码，可用 7-Zip / Bandizip 解压。
"""


def copy_file(src: Path, dst: Path) -> None:
    if not src.is_file():
        raise FileNotFoundError(src)
    shutil.copy2(src, dst)


def build_stage() -> None:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    (STAGE / 'UML').mkdir(parents=True)
    (STAGE / 'UI界面').mkdir()
    (STAGE / 'AI使用记录').mkdir()

    copy_file(LAB2 / '报告' / '实验报告.pdf', STAGE / '实验报告.pdf')

    for f in sorted((LAB2 / 'UML').iterdir()):
        if f.suffix.lower() in ('.png', '.puml') or f.name == 'UML设计说明.md':
            copy_file(f, STAGE / 'UML' / f.name)

    for f in sorted((LAB2 / 'UI界面').glob('*.png')):
        copy_file(f, STAGE / 'UI界面' / f.name)
    copy_file(LAB2 / 'UI' / 'UI设计说明.md', STAGE / 'UI界面' / 'UI设计说明.md')

    copy_file(LAB2 / 'AI使用记录.md', STAGE / 'AI使用记录' / 'AI使用记录.md')
    copy_file(LAB2 / '杂物' / 'AI使用记录_完整过程.md',
              STAGE / 'AI使用记录' / 'AI使用记录_完整过程.md')

    # README 用 UTF-8 BOM，Windows 记事本打开中文不乱码
    (STAGE / 'README.txt').write_text(README, encoding='utf-8-sig')


def build_zip(zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for dirpath, dirnames, filenames in os.walk(STAGE):
            dirnames.sort()
            for fn in sorted(filenames):
                full = Path(dirpath) / fn
                rel = full.relative_to(STAGE.parent).as_posix()
                st = full.stat()
                zi = zipfile.ZipInfo(rel, date_time=time.localtime(st.st_mtime)[:6])
                zi.create_system = 0          # MS-DOS，兼容 Windows 解压
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.external_attr = 0o600 << 16
                with z.open(zi, 'w') as dst:
                    dst.write(full.read_bytes())


def verify(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()
        names = [i.filename for i in infos]
        print('条目数：', len(infos))
        print('压缩包大小：%.2f MB' % (zip_path.stat().st_size / 1024 / 1024))
        print('sha256：', hashlib.sha256(zip_path.read_bytes()).hexdigest())

        bad_flag = [i.filename for i in infos
                    if any(ord(c) > 127 for c in i.filename) and not (i.flag_bits & 0x800)]
        print('非 ASCII 文件名未设置 UTF-8 标志：', bad_flag or '无')

        required = ['实验报告.pdf', 'README.txt']
        for n in required:
            assert any(x.endswith('/' + n) for x in names), n
        assert sum(x.endswith('.puml') for x in names) == 11, 'puml 数量不对'
        assert sum(x.endswith('.png') and '/UML/' in x for x in names) == 11, 'UML png 数量不对'
        assert sum(x.endswith('.png') and '/UI界面/' in x for x in names) == 9, 'UI png 数量不对'
        forbidden = ('杂物/', '.svg', '生成UI.py', '00_设计基线', '进度记录', '报告框架大纲')
        print('禁止项：', [x for x in names if any(k in x for k in forbidden)] or '无')


def main() -> None:
    build_stage()
    zip_path = OUT_DIR / f'{NAME}.zip'
    build_zip(zip_path)
    verify(zip_path)
    print('输出：', zip_path)


if __name__ == '__main__':
    main()
