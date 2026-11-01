#!/usr/bin/env bash
# 导出实验报告.pdf：pandoc -> 修中文引号/图片尺寸/表格列宽/断行 -> xelatex 两遍
set -euo pipefail
cd "$(dirname "$0")"

pandoc 实验报告.md -s -o /tmp/lab2-report.tex --to latex --pdf-engine=xelatex \
  --highlight-style=tango \
  --toc --toc-depth=2 \
  -H pdf-样式.tex \
  -V geometry:a4paper -V geometry:margin=2.1cm -V fontsize=10pt \
  -V mainfont="Noto Serif CJK SC" -V monofont="JetBrains Mono"

python3 - <<'PY'
import re

p = '/tmp/lab2-report.tex'
s = open(p, encoding='utf-8').read()

# 1) 中文弯引号：pandoc 会写成 LaTeX 的 `` / ''，CJK 字体没有这组连字
s = s.replace('``', '“').replace("''", '”')

# 2) 图片统一限制宽高，宽图和高图都不会冲出页面
s = re.sub(
    r'\\includegraphics\{([^}]+)\}',
    r'\\includegraphics[width=\\linewidth,height=0.80\\textheight,keepaspectratio]{\1}',
    s
)

# 2.1) 图注去掉 LaTeX 自动编号（标题文字里已有“图 x-y”）
s = s.replace(r'\caption{', r'\caption*{')

# 2.2) 核心业务类图内容多，单独横排一页，文字更清楚
s = re.sub(
    r'(\\begin\{figure\}\s*\\centering\s*\\includegraphics\[[^\]]*\]\{\.\./UML/UML类图\.png\}.*?\\end\{figure\})',
    lambda m: '\\begin{landscape}\n' + m.group(1) + '\n\\end{landscape}',
    s, count=1, flags=re.S
)

# 2.3) 目录单独一页
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

# 4) 每张表按内容分配列宽（单位：\linewidth）
#    顺序与报告中的 14 张表一致；总和已扣掉 tabcolsep，保证不超版心。
width_specs = [
    [0.09, 0.37, 0.32, 0.16],              # 1.2 用户角色
    [0.16, 0.56, 0.24],                    # 1.3 业务模块
    [0.34, 0.16, 0.46],                    # 1.4 质量约束
    [0.07, 0.16, 0.51, 0.20],              # 2.3 模块划分
    [0.40, 0.57],                          # 2.3 与实验一模块对应
    [0.10, 0.12, 0.47, 0.25],              # 3 UML 图总览
    [0.08, 0.24, 0.12, 0.50],              # 4.1 UI 九屏
    [0.06, 0.15, 0.25, 0.29, 0.17],        # 5.2 AI 使用总览
    [0.06, 0.23, 0.21, 0.25, 0.17],        # 5.3 架构阶段复盘
    [0.27, 0.12, 0.18, 0.37],              # 5.4.3 任务类型
    [0.12, 0.25, 0.33, 0.24],              # 5.4.3 工作流
    [0.09, 0.19, 0.12, 0.13, 0.09, 0.28],  # 附录 A 需求追踪表
    [0.18, 0.79],                          # 附录 B 关键提交
    [0.06, 0.29, 0.43, 0.16],              # 附录 C AI 索引
]

pat = re.compile(r'\\begin\{longtable\}\[\]\{@\{\}([lcr]+)@\{\}\}.*?\\end\{longtable\}', re.S)
blocks = list(pat.finditer(s))
assert len(blocks) == len(width_specs), f'表格数量 {len(blocks)} 与列宽配置 {len(width_specs)} 不一致'

# 逐个表格处理；从后往前替换，避免偏移失效
for m, widths in reversed(list(zip(blocks, width_specs))):
    block = m.group(0)
    n = len(m.group(1))
    assert n == len(widths), f'表格列数 {n} 与列宽配置 {len(widths)} 不一致'

    # 去掉 pandoc 的 minipage 包装，统一改成 p{} 定宽列
    block = re.sub(r'\\begin\{minipage\}\[[bt]\]\{[0-9.]+\\columnwidth\}\\raggedright', '', block)
    block = block.replace('\\end{minipage}', '')

    pcols = ''.join(r'>{\raggedright\arraybackslash}p{%.3f\linewidth}' % w for w in widths)
    new_begin = r'\begin{longtable}{@{}' + pcols + '@{}}'
    block = re.sub(
        r'\\begin\{longtable\}\[\]\{@\{\}[lcr]+@\{\}\}',
        lambda _: new_begin, block, count=1
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

open(p, 'w', encoding='utf-8').write(s)
print('LaTeX 后处理完成')
PY

xelatex -interaction=nonstopmode -halt-on-error -output-directory=/tmp /tmp/lab2-report.tex >/tmp/lab2-xelatex-1.log 2>&1
xelatex -interaction=nonstopmode -halt-on-error -output-directory=/tmp /tmp/lab2-report.tex >/tmp/lab2-xelatex-2.log 2>&1
cp /tmp/lab2-report.pdf 实验报告.pdf

echo "=== 页数与纸张 ==="
pdfinfo 实验报告.pdf | grep -E "Pages|Page size"
echo "=== 缺字数（应为 0）==="
grep -c "Missing character" /tmp/lab2-report.log || true
echo "=== 编译错误（应为 0）==="
grep -cE "^!|Emergency" /tmp/lab2-report.log || true
echo "=== 溢出数（供检查）==="
grep -c "Overfull \\\\hbox" /tmp/lab2-report.log || true
