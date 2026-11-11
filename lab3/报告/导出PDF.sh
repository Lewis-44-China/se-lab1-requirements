#!/usr/bin/env bash
# 导出实验报告.pdf：pandoc -> 修中文引号/图片尺寸/表格列宽/断行 -> xelatex 两遍
# 沿用实验二 lab2/报告/导出PDF.sh 的方案。
set -euo pipefail
cd "$(dirname "$0")"

pandoc 实验报告.md -s -o /tmp/lab3-report.tex --to latex --pdf-engine=xelatex \
  --highlight-style=tango \
  --toc --toc-depth=2 \
  -H pdf-样式.tex \
  -V geometry:a4paper -V geometry:margin=2.1cm -V fontsize=10pt \
  -V mainfont="Noto Serif CJK SC" -V monofont="JetBrains Mono"

python3 - <<'PY'
import re

p = '/tmp/lab3-report.tex'
s = open(p, encoding='utf-8').read()

# 0) 先保护代码块：verbatim / Highlighting 里的中文标点不能做断行替换，
#    否则 \allowbreak{} 会作为字面文本显示出来
code_blocks = []

def stash(m):
    code_blocks.append(m.group(0))
    return f'@@LAB3CODE{len(code_blocks) - 1}@@'

s = re.sub(r'\\begin\{verbatim\}.*?\\end\{verbatim\}', stash, s, flags=re.S)
s = re.sub(r'\\begin\{Highlighting\}.*?\\end\{Highlighting\}', stash, s, flags=re.S)

# 1) 中文弯引号：pandoc 会写成 LaTeX 的 `` / ''，CJK 字体没有这组连字
s = s.replace('``', '“').replace("''", '”')

# 2) 图片统一限制宽高，宽图和高图都不会冲出页面
s = re.sub(
    r'\\includegraphics\{([^}]+)\}',
    r'\\includegraphics[width=\\linewidth,height=0.80\\textheight,keepaspectratio]{\1}',
    s,
)

# 2.1) 图注去掉 LaTeX 自动编号（标题文字里已有“图 4-1”）
s = s.replace(r'\caption{', r'\caption*{')

# 2.2) 目录单独一页
s = s.replace(r'\tableofcontents', '\\tableofcontents\n\\newpage', 1)

# 3) 行内代码允许在 / _ . - 和驼峰处断行；中文顿号/逗号/分号后也允许断行
def fix_texttt(m):
    text = m.group(1)
    text = text.replace('\\_', '\\_\\allowbreak{}')
    text = text.replace('/', '/\\allowbreak{}')
    text = text.replace('.', '.\\allowbreak{}')
    text = text.replace('-', '-\\allowbreak{}')
    text = re.sub(r'(?<=[a-z])(?=[A-Z])', r'\\allowbreak{}', text)
    return r'\texttt{%s}' % text

s = re.sub(r'\\texttt\{([^{}]*)\}', fix_texttt, s)
s = s.replace('、', '、\\allowbreak{}').replace('，', '，\\allowbreak{}').replace('；', '；\\allowbreak{}')

# 4) 报告中 3 张表都是两列，按内容分配列宽（单位：\linewidth）
width_specs = [
    [0.21, 0.76],  # 0. 基本信息：项目 / 内容
    [0.37, 0.60],  # 1. 目录职责：目录文件 / 职责
    [0.19, 0.78],  # 5. 提交记录：提交 / 内容
]

pat = re.compile(r'\\begin\{longtable\}\[\]\{@\{\}([lcr]+)@\{\}\}.*?\\end\{longtable\}', re.S)
blocks = list(pat.finditer(s))
assert len(blocks) == len(width_specs), f'表格数量 {len(blocks)} 与列宽配置 {len(width_specs)} 不一致'

for m, widths in reversed(list(zip(blocks, width_specs))):
    block = m.group(0)
    n = len(m.group(1))
    assert n == len(widths), f'表格列数 {n} 与列宽配置 {len(widths)} 不一致'

    # 去掉 pandoc 的 minipage 包装，统一改成 p{} 定宽列
    block = re.sub(
        r'\\begin\{minipage\}\[[bt]\]\{[0-9.]+\\columnwidth\}\\raggedright',
        '',
        block,
    )
    block = block.replace('\\end{minipage}', '')

    pcols = ''.join(r'>{\raggedright\arraybackslash}p{%.3f\linewidth}' % w for w in widths)
    new_begin = r'\begin{longtable}{@{}' + pcols + '@{}}'
    block = re.sub(
        r'\\begin\{longtable\}\[\]\{@\{\}[lcr]+@\{\}\}',
        lambda _: new_begin,
        block,
        count=1,
    )

    # 数据行之间加横线，便于阅读
    marker = r'\endhead'
    pos = block.find(marker)
    if pos >= 0:
        head = block[:pos + len(marker)]
        body = block[pos + len(marker):]
        body = body.replace(r'\tabularnewline', r'\tabularnewline\hline')
        body = re.sub(r'\\hline\s*\\bottomrule', r'\\bottomrule', body)
        block = head + body

    s = s[:m.start()] + block + s[m.end():]

# 恢复代码块
for i, block in enumerate(code_blocks):
    s = s.replace(f'@@LAB3CODE{i}@@', block)

open(p, 'w', encoding='utf-8').write(s)
print('LaTeX 后处理完成')
PY

xelatex -interaction=nonstopmode -halt-on-error -output-directory=/tmp /tmp/lab3-report.tex >/tmp/lab3-xelatex-1.log 2>&1
xelatex -interaction=nonstopmode -halt-on-error -output-directory=/tmp /tmp/lab3-report.tex >/tmp/lab3-xelatex-2.log 2>&1
cp /tmp/lab3-report.pdf 实验报告.pdf

echo "=== 页数与纸张 ==="
pdfinfo 实验报告.pdf | grep -E "Pages|Page size"
echo "=== 缺字数（应为 0）==="
grep -c "Missing character" /tmp/lab3-report.log || true
echo "=== 编译错误（应为 0）==="
grep -cE "^!|Emergency" /tmp/lab3-report.log || true
echo "=== 溢出数（供检查）==="
grep -c "Overfull \\\\hbox" /tmp/lab3-report.log || true
