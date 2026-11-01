# -*- coding: utf-8 -*-
"""生成实验二三屏 UI 样例 SVG（供导入 Figma 调整）"""
from html import escape
from pathlib import Path

W, H = 1440, 900
FONT = "Noto Sans CJK SC, Microsoft YaHei, sans-serif"
C = {
    "bg": "#F8FAFC", "surface": "#FFFFFF", "primary": "#2563EB",
    "primary_dark": "#1D4ED8", "blue_tint": "#EFF6FF", "text": "#0F172A",
    "sub": "#475569", "muted": "#94A3B8", "border": "#E2E8F0",
    "success": "#059669", "success_bg": "#ECFDF5", "warning": "#B45309",
    "warning_bg": "#FFFBEB", "danger": "#DC2626", "danger_bg": "#FEF2F2",
    "purple": "#7C3AED", "teal": "#0D9488", "orange": "#EA580C",
}


def esc(s):
    return escape(str(s), quote=True)


def rect(x, y, w, h, fill, rx=0, stroke=None, sw=1, opacity=1.0):
    s = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" rx="{rx}" opacity="{opacity}"'
    if stroke:
        s += f' stroke="{stroke}" stroke-width="{sw}"'
    return s + '/>'


def line(x1, y1, x2, y2, color=C["border"], sw=1, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ''
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{sw}"{d}/>'


def text(x, y, s, size=14, color=C["text"], weight=400, anchor="start", spacing=None):
    sp = f' letter-spacing="{spacing}"' if spacing else ''
    return (f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" '
            f'font-weight="{weight}" fill="{color}" text-anchor="{anchor}"{sp}>{esc(s)}</text>')


def lines(x, y, items, size=14, color=C["text"], weight=400, leading=22):
    return "".join(text(x, y + i * leading, s, size, color, weight) for i, s in enumerate(items))


def button(x, y, w, h, label, kind="primary", size=15):
    if kind == "primary":
        bg, fg, border = C["primary"], "#FFFFFF", None
    elif kind == "secondary":
        bg, fg, border = "#FFFFFF", C["primary"], C["primary"]
    elif kind == "ghost":
        bg, fg, border = C["blue_tint"], C["primary"], None
    else:
        bg, fg, border = C["surface"], C["text"], C["border"]
    return (rect(x, y, w, h, bg, 10, border, 1) +
            text(x + w / 2, y + h / 2 + 5, label, size, fg, 600, "middle"))


def input_box(x, y, w, h, placeholder, label=None, value=None, icon=None):
    out = ""
    if label:
        out += text(x, y - 10, label, 12, C["sub"], 500)
    out += rect(x, y, w, h, C["bg"], 10, C["border"])
    tx = x + 16
    if icon:
        out += icon(x + 18, y + h / 2, 9, C["muted"])
        tx = x + 42
    if value:
        out += text(tx, y + h / 2 + 5, value, 14, C["text"], 400)
    else:
        out += text(tx, y + h / 2 + 5, placeholder, 14, C["muted"], 400)
    return out


def badge(x, y, label, fg, bg, size=11):
    w = max(54, len(label) * size + 22)
    return (rect(x, y, w, 24, bg, 12) +
            text(x + w / 2, y + 16, label, size, fg, 600, "middle"))


def circle(cx, cy, r, fill, opacity=1):
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{fill}" opacity="{opacity}"/>'


def icon_search(x, y, r=9, color=C["muted"]):
    return (f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="{color}" stroke-width="2"/>'
            f'<path d="M{x+r-1} {y+r-1} l{int(r*0.8)} {int(r*0.8)}" stroke="{color}" stroke-width="2" stroke-linecap="round"/>')


def icon_check(x, y, r=10, color="#FFFFFF"):
    return (circle(x, y, r, color, 1) +
            f'<path d="M{x-4} {y} l3 3 l6 -7" fill="none" stroke="{C["primary"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')


def icon_person(x, y, r=8, color=C["muted"]):
    return (f'<circle cx="{x}" cy="{y-4}" r="{r*0.55}" fill="none" stroke="{color}" stroke-width="2"/>'
            f'<path d="M{x-9} {y+10} c0 -7 18 -7 18 0" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round"/>')


def icon_calendar(x, y, color=C["muted"]):
    return (rect(x-9, y-8, 18, 16, "none", 3, color, 2) +
            line(x-9, y-3, x+9, y-3, color, 2) +
            line(x-5, y-11, x-5, y-6, color, 2) +
            line(x+5, y-11, x+5, y-6, color, 2))


def svg_doc(body, defs=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}">\n<defs>{defs}</defs>\n{body}\n</svg>\n')


def screen_login():
    defs = ('<linearGradient id="brand" x1="0" y1="0" x2="1" y2="1">'
            '<stop offset="0%" stop-color="#1D4ED8"/><stop offset="100%" stop-color="#2563EB"/>'
            '</linearGradient>')
    b = [rect(0, 0, W, H, "#F1F5F9")]
    # 左侧品牌区
    b.append(rect(0, 0, 560, H, "url(#brand)"))
    b.append(circle(80, 120, 190, "#FFFFFF", 0.06))
    b.append(circle(500, 760, 240, "#FFFFFF", 0.05))
    b.append(circle(470, 170, 70, "#FFFFFF", 0.08))
    b.append(rect(56, 54, 44, 44, "#FFFFFF", 12))
    b.append(f'<path d="M68 66 h20 v20 h-20 z" fill="none" stroke="{C["primary"]}" stroke-width="2"/>'
             f'<path d="M74 66 v20 M82 66 v20" stroke="{C["primary"]}" stroke-width="1.5" stroke-dasharray="2 2"/>')
    b.append(text(116, 82, "活动票务", 24, "#FFFFFF", 700))
    b.append(text(116, 102, "ACTIVITY TICKETING", 10, "#DBEAFE", 500, spacing="2"))
    b.append(text(56, 330, "不辜负每一份热爱", 40, "#FFFFFF", 700))
    b.append(text(56, 380, "活动发布 · 报名购票 · 候补递补 · 检票管理", 15, "#DBEAFE", 400))
    for i, s in enumerate(["四类角色，权限边界清楚", "名额实时，报名不超发", "候补递补，全程有通知"]):
        y = 500 + i * 48
        b.append(icon_check(66, y - 5, 10))
        b.append(text(88, y, s, 14, "#FFFFFF", 500))
    b.append(text(56, 820, "课程项目 · 活动票务与报名系统", 12, "#BFDBFE", 400))

    # 右侧登录区
    b.append(text(640, 124, "欢迎回来", 30, C["text"], 700))
    b.append(text(640, 154, "登录后继续报名或管理活动", 14, C["sub"]))
    b.append(rect(640, 190, 400, 440, C["surface"], 16, C["border"]))
    b.append(text(672, 232, "登录", 16, C["primary"], 700))
    b.append(rect(672, 242, 30, 3, C["primary"], 2))
    b.append(input_box(672, 304, 336, 48, "请输入手机号", "手机号", icon=icon_person))
    b.append(input_box(672, 390, 336, 48, "请输入密码", "密码"))
    b.append(f'<path d="M972 414 c6 -9 22 -9 28 0 c-6 9 -22 9 -28 0z" fill="none" stroke="{C["muted"]}" stroke-width="1.6"/><circle cx="986" cy="414" r="3" fill="{C["muted"]}"/>')
    b.append(rect(672, 462, 14, 14, C["surface"], 3, C["border"]))
    b.append(text(694, 474, "记住我", 12, C["sub"]))
    b.append(button(672, 494, 336, 48, "登录", "primary"))
    b.append(text(840, 610, "管理员 / 检票员登录入口", 11, C["muted"], 500, "middle"))

    # 右侧注册引导卡
    b.append(rect(1080, 190, 300, 440, C["surface"], 16, C["border"]))
    b.append(text(1104, 230, "注册账号", 20, C["text"], 700))
    b.append(text(1104, 256, "选择身份后填写手机号与密码", 12, C["sub"]))
    # 角色卡：参与者
    b.append(rect(1104, 282, 252, 74, C["blue_tint"], 10, C["primary"]))
    b.append(circle(1128, 319, 16, C["primary"]))
    b.append(icon_person(1128, 319, 9, "#FFFFFF"))
    b.append(text(1154, 312, "参与者", 14, C["text"], 700))
    b.append(text(1154, 332, "报名、购票、候补", 11, C["muted"]))
    b.append(icon_check(1332, 319, 9))
    # 角色卡：组织者
    b.append(rect(1104, 368, 252, 74, C["surface"], 10, C["border"]))
    b.append(circle(1128, 405, 16, "#E2E8F0"))
    b.append(icon_calendar(1128, 405, C["sub"]))
    b.append(text(1154, 398, "组织者", 14, C["text"], 700))
    b.append(text(1154, 418, "创建活动、管理名单", 11, C["muted"]))
    b.append(text(1104, 472, "管理员 / 检票员账号由平台预创建", 11, C["muted"]))
    b.append(button(1104, 500, 252, 44, "去注册", "secondary"))
    b.append(text(640, 700, "© 2026 活动票务 · 软件工程实验二", 11, C["muted"]))
    return svg_doc("".join(b), defs)



def top_nav(active="活动", role="参与者", name="林同学", avatar="林", breadcrumb=None, items=None):
    b = [rect(0, 0, W, 72, C["surface"]), line(0, 72, W, 72, C["border"])]
    b.append(rect(32, 19, 34, 34, C["primary"], 9))
    b.append(f'<path d="M41 28 h16 v16 h-16 z" fill="none" stroke="#FFFFFF" stroke-width="1.6"/>'
             f'<path d="M46 28 v16 M52 28 v16" stroke="#FFFFFF" stroke-width="1.2" stroke-dasharray="2 2"/>')
    b.append(text(78, 43, "活动票务", 18, C["text"], 700))
    if breadcrumb:
        b.append(text(210, 43, breadcrumb, 12, C["muted"]))
    else:
        if items is None:
            items = [("活动", 220), ("我的票", 285), ("通知", 355)]
        for label, x in items:
            color = C["primary"] if label == active else C["sub"]
            weight = 600 if label == active else 400
            b.append(text(x, 43, label, 14, color, weight))
            if label == active:
                b.append(rect(x, 54, 28, 3, C["primary"], 2))
    b.append(rect(1178, 24, 74, 24, C["blue_tint"], 12))
    b.append(text(1215, 40, role, 11, C["primary"], 600, "middle"))
    b.append(circle(1288, 36, 17, "#DBEAFE"))
    b.append(text(1288, 41, avatar, 13, C["primary_dark"], 700, "middle"))
    b.append(text(1312, 41, name, 13, C["text"], 500))
    return "".join(b)


def screen_activity():
    defs = (
        '<linearGradient id="g1" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#2563EB"/><stop offset="100%" stop-color="#7C3AED"/></linearGradient>'
        '<linearGradient id="g2" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#0D9488"/><stop offset="100%" stop-color="#0F766E"/></linearGradient>'
        '<linearGradient id="g3" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#EA580C"/><stop offset="100%" stop-color="#F59E0B"/></linearGradient>'
        '<linearGradient id="g4" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#475569"/><stop offset="100%" stop-color="#7C3AED"/></linearGradient>'
    )
    b = [rect(0, 0, W, H, C["bg"]), top_nav("活动")]
    b.append(text(32, 126, "发现活动", 30, C["text"], 700))
    b.append(text(32, 154, "按时间、类型和状态找到想参加的活动", 14, C["sub"]))
    b.append(rect(32, 178, 1376, 56, C["surface"], 12, C["border"]))
    b.append(icon_search(58, 206, 9))
    b.append(text(82, 212, "搜索活动名称、地点或组织者", 13, C["muted"]))
    b.append(line(392, 192, 392, 220, C["border"]))
    for i, (label, active) in enumerate([("全部", True), ("音乐", False), ("戏剧", False), ("讲座", False)]):
        x = 408 + i * 56
        if active:
            b.append(rect(x, 195, 48, 24, C["primary"], 12))
            b.append(text(x + 24, 211, label, 11, "#FFFFFF", 600, "middle"))
        else:
            b.append(text(x + 18, 211, label, 11, C["sub"], 400, "middle"))
    b.append(line(632, 192, 632, 220, C["border"]))
    for x, label, chev in [(650, "时间范围", 70), (778, "全部状态", 70), (906, "全部场次", 70), (1034, "全部票种", 70), (1162, "时间：最新在前", 96)]:
        b.append(text(x, 211, label, 11, C["sub"]))
        b.append(f'<path d="M{x+chev} 207 l4 4 l4 -4" fill="none" stroke="{C["muted"]}" stroke-width="1.5"/>')

    cards = [
        ("城市音乐节 · 夏日专场", "11月8日 19:30 · 南京 · 新庄国展中心", "音乐 / 户外", "¥120 起", "余 36", "售票中", C["success"], C["success_bg"], "g1", "乐", True),
        ("沉浸式戏剧《夜航》", "11月12日 19:30 · 南京 · 鼓楼剧场", "戏剧 / 沉浸式", "¥180 起", "余 12", "即将售罄", C["warning"], C["warning_bg"], "g2", "剧", False),
        ("古典音乐会 · 秋夜", "11月16日 19:30 · 南京 · 南京艺术学院音乐厅", "音乐 / 古典", "¥80 起", "余 60", "售票中", C["success"], C["success_bg"], "g3", "音", False),
        ("设计沙龙：AI 与创作", "11月20日 14:00 · 南京 · 创意产业园", "讲座 / 设计", "¥60 起", "已售罄", "可候补", C["warning"], C["warning_bg"], "g4", "讲", False),
    ]
    for i, (title, meta, tags, price, remain, status, sfg, sbg, gid, char, selected) in enumerate(cards):
        y = 264 + i * 132
        b.append(rect(32, y, 800, 116, C["blue_tint"] if selected else C["surface"], 14, C["primary"] if selected else C["border"], 1.5 if selected else 1))
        b.append(rect(48, y + 16, 144, 84, f"url(#{gid})", 10))
        b.append(text(120, y + 68, char, 42, "#FFFFFF", 700, "middle"))
        b.append(text(208, y + 34, title, 17, C["text"], 700))
        b.append(text(208, y + 58, meta, 12, C["sub"]))
        b.append(badge(208, y + 72, tags.split(" / ")[0], C["primary"], C["blue_tint"], 10))
        b.append(text(292, y + 82, tags.split(" / ")[1], 10, C["muted"]))
        b.append(text(792, y + 34, price, 16, C["primary"], 700, "end"))
        b.append(text(792, y + 58, remain, 12, C["success"] if "售罄" not in remain else C["danger"], 600, "end"))
        b.append(badge(642, y + 16, status, sfg, sbg, 10))

    b.append(rect(852, 264, 556, 620, C["surface"], 16, C["border"]))
    b.append(rect(852, 264, 556, 150, "url(#g1)", 16))
    b.append(rect(852, 394, 556, 20, C["surface"], 0))
    b.append(badge(876, 284, "音乐", "#FFFFFF", "rgba(255,255,255,0.22)", 10))
    b.append(text(876, 364, "城市音乐节 · 夏日专场", 24, "#FFFFFF", 700))
    b.append(text(876, 390, "11月8日 19:30 · 南京 · 新庄国展中心", 12, "#DBEAFE"))
    b.append(text(876, 456, "城市音乐节 · 夏日专场", 22, C["text"], 700))
    b.append(text(876, 482, "主办：城市文化中心", 12, C["sub"]))
    b.append(rect(876, 504, 504, 1, C["border"]))
    b.append(text(876, 540, "场次票种", 14, C["primary"], 700))
    b.append(rect(876, 550, 56, 3, C["primary"], 2))
    b.append(text(950, 540, "活动详情", 14, C["muted"]))
    b.append(rect(876, 570, 164, 34, C["blue_tint"], 8, C["primary"]))
    b.append(text(958, 592, "11月8日 19:30", 12, C["primary"], 600, "middle"))
    b.append(rect(1050, 570, 164, 34, C["surface"], 8, C["border"]))
    b.append(text(1132, 592, "11月9日 19:30", 12, C["sub"], 400, "middle"))
    b.append(text(876, 638, "票种", 11, C["muted"], 500))
    b.append(text(1080, 638, "价格", 11, C["muted"], 500))
    b.append(text(1170, 638, "余票", 11, C["muted"], 500))
    b.append(rect(876, 650, 504, 48, C["bg"], 8))
    b.append(text(892, 680, "VIP 票", 13, C["text"], 600))
    b.append(text(1080, 680, "¥220", 13, C["text"], 600))
    b.append(text(1170, 680, "余 8", 12, C["success"], 600))
    b.append(button(1288, 660, 76, 28, "选择", "ghost", 11))
    b.append(rect(876, 706, 504, 48, C["surface"], 8, C["border"]))
    b.append(text(892, 736, "普通票", 13, C["text"], 600))
    b.append(text(1080, 736, "¥120", 13, C["text"], 600))
    b.append(text(1170, 736, "余 28", 12, C["success"], 600))
    b.append(button(1288, 716, 76, 28, "选择", "secondary", 11))
    b.append(text(876, 780, "名额实时更新，以提交报名时的结果为准", 11, C["muted"]))
    b.append(rect(876, 796, 504, 44, C["warning_bg"], 8))
    b.append(text(892, 823, "报名截止 11月7日 23:59 · 退票截止 11月7日 18:00", 11, C["warning"]))
    b.append(button(876, 852, 504, 28, "立即报名", "primary", 12))
    return svg_doc("".join(b), defs)


def screen_checkout():
    defs = ('<linearGradient id="gc" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#2563EB"/><stop offset="100%" stop-color="#7C3AED"/></linearGradient>')
    b = [rect(0, 0, W, H, C["bg"]), top_nav("活动", breadcrumb="活动 / 城市音乐节 · 夏日专场 / 报名")]
    b.append(text(32, 126, "完成报名", 30, C["text"], 700))
    b.append(text(32, 154, "确认报名信息并完成支付标记", 14, C["sub"]))
    steps = [("1", "选择活动", True), ("2", "填写报名", True), ("3", "完成", False)]
    for i, (num, label, done) in enumerate(steps):
        x = 32 + i * 210
        color = C["primary"] if done else C["muted"]
        b.append(circle(x + 14, 190, 14, C["primary"] if done else C["surface"], 1 if done else 0))
        if not done:
            b.append(f'<circle cx="{x+14}" cy="190" r="13" fill="none" stroke="{C["border"]}" stroke-width="1.5"/>')
        b.append(text(x + 14, 195, num, 12, "#FFFFFF" if done else C["muted"], 700, "middle"))
        b.append(text(x + 38, 195, label, 12, color, 600 if done else 400))
        if i < 2:
            b.append(line(x + 112, 190, x + 196, 190, C["border"]))

    b.append(rect(32, 220, 820, 620, C["surface"], 16, C["border"]))
    b.append(rect(56, 244, 100, 100, "url(#gc)", 12))
    b.append(text(106, 306, "乐", 34, "#FFFFFF", 700, "middle"))
    b.append(text(176, 270, "城市音乐节 · 夏日专场", 18, C["text"], 700))
    b.append(text(176, 296, "11月8日 19:30 · 新庄国展中心", 12, C["sub"]))
    b.append(text(176, 318, "普通票 · 1 张", 12, C["sub"]))
    b.append(badge(700, 258, "候补登记", C["warning"], C["warning_bg"], 10))
    b.append(line(56, 360, 828, 360, C["border"]))
    b.append(text(56, 392, "选择票种", 15, C["text"], 700))
    b.append(rect(56, 410, 376, 100, C["warning_bg"], 12, C["warning"], 1.5))
    b.append(text(76, 442, "普通票", 15, C["text"], 700))
    b.append(text(76, 466, "¥120 / 张", 13, C["sub"]))
    b.append(badge(330, 424, "已售罄", C["danger"], C["danger_bg"], 10))
    b.append(text(76, 490, "点击加入候补队列", 11, C["warning"]))
    b.append(rect(448, 410, 376, 100, C["surface"], 12, C["border"]))
    b.append(text(468, 442, "VIP 票", 15, C["text"], 700))
    b.append(text(468, 466, "¥220 / 张", 13, C["sub"]))
    b.append(badge(722, 424, "余 2", C["success"], C["success_bg"], 10))
    b.append(text(468, 490, "可直接报名", 11, C["success"]))
    b.append(text(56, 530, "报名信息", 15, C["text"], 700))
    b.append(input_box(56, 560, 370, 44, "请输入姓名", "姓名", value="林同学"))
    b.append(input_box(448, 560, 376, 44, "请输入手机号", "手机号", value="138****8888"))
    b.append(text(56, 624, "一单一张，不支持代报名；手机号仅用于报名和检票", 11, C["muted"]))
    b.append(text(56, 660, "支付标记", 15, C["text"], 700))
    b.append(rect(56, 678, 18, 18, C["primary"], 6))
    b.append(f'<path d="M60 687 l4 4 l7 -8" fill="none" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round"/>')
    b.append(text(84, 692, "确认支付标记（平台内，不接真实支付）", 12, C["sub"]))
    b.append(text(828, 692, "应付 ¥120", 20, C["text"], 700, "end"))
    b.append(rect(56, 714, 776, 58, C["warning_bg"], 10))
    b.append(text(72, 738, "候补截止 11月7日 23:59；递补成功自动转为已购票并通知；未递补成功全额退款", 11, C["warning"]))
    b.append(text(72, 758, "候补成功只是加入候补队列，不保证最终买到票。", 11, C["muted"]))
    b.append(button(56, 790, 776, 44, "加入候补并支付标记", "primary", 14))
    b.append(text(444, 852, "返回活动详情", 11, C["primary"], 500, "middle"))
    b.append(rect(876, 220, 532, 620, C["surface"], 16, C["border"]))
    b.append(text(900, 258, "候补说明", 18, C["text"], 700))
    b.append(text(900, 282, "按票种排队，先到先得", 12, C["sub"]))
    steps = [("1", "加入候补队列", "按入队时间排序，先到先得"), ("2", "等待名额释放", "有人退票后，按队首顺序递补"), ("3", "递补或退款", "递补成功生成已购票；未成功全额退款")]
    for i, (num, title, desc) in enumerate(steps):
        y = 326 + i * 92
        b.append(circle(920, y, 13, C["blue_tint"]))
        b.append(text(920, y + 4, num, 12, C["primary"], 700, "middle"))
        b.append(text(946, y + 4, title, 14, C["text"], 600))
        b.append(text(946, y + 26, desc, 11, C["sub"]))
        if i < 2:
            b.append(line(920, y + 15, 920, y + 77, C["border"], 1, "4 4"))
    b.append(rect(900, 598, 484, 72, C["bg"], 10))
    b.append(text(918, 624, "候补状态", 11, C["muted"]))
    b.append(text(918, 650, "未候补", 20, C["text"], 700))
    b.append(text(1040, 624, "下一步", 11, C["muted"]))
    b.append(text(1040, 650, "支付后加入候补队列", 13, C["sub"], 500))
    b.append(text(900, 708, "有票时怎么办？", 13, C["text"], 700))
    b.append(text(900, 730, "若其他票种仍有余票，可直接选择有票票种报名，无需候补。", 11, C["sub"]))
    b.append(rect(900, 752, 484, 64, C["blue_tint"], 10))
    b.append(text(918, 776, "提示", 11, C["primary"], 700))
    b.append(text(918, 796, "候补记录独立于报名记录；递补成功才生成“已购票”报名记录。", 11, C["sub"]))
    return svg_doc("".join(b), defs)



def screen_my_tickets():
    b = [rect(0, 0, W, H, C["bg"]), top_nav("我的票", "参与者", items=[("活动", 220), ("我的票", 285), ("通知", 355)])]
    b.append(text(32, 126, "我的票", 30, C["text"], 700))
    b.append(text(32, 154, "查看报名、候补与退款记录；已购票表示有效票（待检票）", 14, C["sub"]))
    positions = [32, 104, 176, 248, 320, 392]
    for i, (label, active) in enumerate([("全部", True), ("已购票", False), ("已检票", False), ("候补中", False), ("已结束", False), ("已取消/已退票", False)]):
        x = positions[i]
        if active:
            b.append(rect(x, 178, 56, 26, C["primary"], 13))
            b.append(text(x + 28, 195, label, 11, "#FFFFFF", 600, "middle"))
        else:
            b.append(text(x + 8, 195, label, 11, C["sub"], 400, "middle"))
    cards = [
        ("城市音乐节 · 夏日专场", "11月8日 19:30 · 新庄国展中心", "普通票 · 1 张", "已购票", C["success"], C["success_bg"], "乐", "g1", "有效票 · 待检票 · 退票截止 11月7日 18:00", "申请退票"),
        ("沉浸式戏剧《夜航》", "11月12日 19:30 · 鼓楼剧场", "VIP 票 · 1 张", "已检票", C["primary"], C["blue_tint"], "剧", "g2", "已检票 · 不可退票", "查看详情"),
        ("古典音乐会 · 秋夜", "11月16日 19:30 · 南京艺术学院音乐厅", "普通票 · 候补", "候补中", C["warning"], C["warning_bg"], "音", "g3", "入队 11-01 09:20 · 候补截止 11-05 23:59", "取消候补"),
        ("设计沙龙：AI 与创作", "11月20日 14:00 · 创意产业园", "普通票 · 1 张", "已退票", C["muted"], C["bg"], "讲", "g4", "已退款 ¥60 · 11-01 10:02", "查看详情"),
    ]
    for i, (title, meta, ticket, status, sfg, sbg, char, gid, note, action) in enumerate(cards):
        y = 230 + i * 156
        b.append(rect(32, y, 900, 140, C["surface"], 16, C["border"]))
        b.append(rect(48, y + 16, 128, 108, f"url(#{gid})", 12))
        b.append(text(112, y + 82, char, 38, "#FFFFFF", 700, "middle"))
        b.append(text(196, y + 34, title, 17, C["text"], 700))
        b.append(text(196, y + 58, meta, 11, C["sub"]))
        b.append(text(196, y + 82, ticket, 11, C["sub"]))
        b.append(badge(748, y + 18, status, sfg, sbg, 10))
        b.append(text(196, y + 112, note, 10, C["warning"] if status in ("已购票", "候补中") else C["muted"]))
        b.append(button(704, y + 96, 148, 32, action, "secondary" if action in ("申请退票", "取消候补") else "ghost", 11))
    b.append(rect(956, 230, 452, 560, C["surface"], 16, C["border"]))
    b.append(text(980, 268, "退票与候补说明", 18, C["text"], 700))
    bullets = [
        ("未过退票截止", "可申请退票，退款金额等于支付金额"),
        ("已检票 / 已过截止", "不可退票，记录保留"),
        ("候补中取消", "退全款；候补记录进入终态"),
        ("活动取消", "统一退款；与自行退票在筛选里同组，但卡片显示具体原因"),
        ("记录保留", "报名/候补记录不提供删除"),
    ]
    for i, (t, d) in enumerate(bullets):
        y = 304 + i * 64
        b.append(circle(992, y, 5, C["primary"]))
        b.append(text(1008, y + 5, t, 12, C["text"], 600))
        b.append(text(1008, y + 25, d, 10, C["sub"]))
    b.append(rect(980, 666, 404, 92, C["blue_tint"], 10))
    b.append(text(996, 690, "状态说明", 11, C["primary"], 700))
    b.append(text(996, 710, "“我的票”展示报名记录；“候补中”是候补记录，尚未取得票。", 10, C["sub"]))
    b.append(text(996, 730, "“已购票”是需求里的报名状态，UI 上补充“有效票（待检票）”。", 10, C["sub"]))
    return svg_doc("".join(b), defs_gradient())


def screen_organizer_activities():
    defs = defs_gradient()
    b = [rect(0, 0, W, H, C["bg"]), top_nav("活动管理", "组织者", name="李晨", avatar="李", items=[("活动管理", 220), ("名单统计", 310), ("通知", 400)])]
    b.append(text(32, 126, "活动管理", 30, C["text"], 700))
    b.append(text(32, 154, "创建、提交审核、管理场次票种与取消申请", 14, C["sub"]))
    b.append(button(1236, 110, 172, 42, "创建活动", "primary", 13))
    stats = [("进行中", "2", C["success"], C["success_bg"]), ("待审核", "1", C["warning"], C["warning_bg"]), ("草稿", "1", C["muted"], C["bg"]), ("已结束", "3", C["primary"], C["blue_tint"])]
    for i, (label, value, fg, bg) in enumerate(stats):
        x = 32 + i * 236
        b.append(rect(x, 180, 212, 78, C["surface"], 12, C["border"]))
        b.append(text(x + 18, 208, label, 11, C["muted"]))
        b.append(text(x + 18, 240, value, 24, fg, 700))
        b.append(rect(x + 172, 194, 24, 24, bg, 8))
    # 表格
    b.append(rect(32, 280, 920, 520, C["surface"], 16, C["border"]))
    b.append(text(56, 316, "活动", 11, C["muted"], 500))
    b.append(text(356, 316, "场次", 11, C["muted"], 500))
    b.append(text(436, 316, "状态", 11, C["muted"], 500))
    b.append(text(556, 316, "报名/容量", 11, C["muted"], 500))
    b.append(text(684, 316, "最近更新", 11, C["muted"], 500))
    b.append(text(796, 316, "操作", 11, C["muted"], 500))
    b.append(line(56, 330, 928, 330))
    rows = [
        ("城市音乐节 · 夏日专场", "2 场", "进行中", C["success"], C["success_bg"], "168 / 200", "11-01 14:20", "查看  编辑  申请取消"),
        ("沉浸式戏剧《夜航》", "1 场", "待审核", C["warning"], C["warning_bg"], "0 / 120", "11-01 10:02", "查看"),
        ("设计沙龙：AI 与创作", "1 场", "草稿", C["muted"], C["bg"], "0 / 60", "10-31 18:40", "编辑  提交审核"),
        ("古典音乐会 · 秋夜", "1 场", "已结束", C["primary"], C["blue_tint"], "96 / 100", "10-30 21:00", "查看  名单"),
    ]
    for i, (title, session, status, sfg, sbg, count, updated, actions) in enumerate(rows):
        y = 352 + i * 98
        b.append(text(56, y + 22, title, 14, C["text"], 600))
        b.append(text(356, y + 22, session, 12, C["sub"]))
        b.append(badge(436, y + 6, status, sfg, sbg, 10))
        b.append(text(556, y + 22, count, 12, C["sub"]))
        b.append(text(684, y + 22, updated, 11, C["muted"]))
        b.append(text(796, y + 22, actions, 11, C["primary"], 500))
        b.append(line(56, y + 52, 928, y + 52, C["border"]))
    # 右栏修改规则
    b.append(rect(976, 180, 432, 620, C["surface"], 16, C["border"]))
    b.append(text(1000, 218, "发布后可修改范围", 18, C["text"], 700))
    rules = [
        ("可直接修改", ["描述、图片、标签"], C["success"]),
        ("需重新审核", ["时间、地点", "开售前容量、票价"], C["warning"]),
        ("禁止修改", ["开售后容量、票价"], C["danger"]),
        ("取消活动", ["组织者取消需管理员审批"], C["primary"]),
    ]
    for i, (title, items, color) in enumerate(rules):
        y = 258 + i * 126
        b.append(rect(1000, y - 18, 384, 1, C["border"]))
        b.append(text(1000, y + 4, title, 13, color, 700))
        for j, item in enumerate(items):
            b.append(text(1000, y + 28 + j * 20, "· " + item, 11, C["sub"]))
    return svg_doc("".join(b), defs)


def screen_organizer_roster():
    b = [rect(0, 0, W, H, C["bg"]), top_nav("名单统计", "组织者", name="李晨", avatar="李", items=[("活动管理", 220), ("名单统计", 310), ("通知", 400)])]
    b.append(text(32, 126, "名单与统计", 30, C["text"], 700))
    b.append(text(32, 154, "名单仅本活动组织者可见，手机号遮挡", 14, C["sub"]))
    b.append(rect(32, 178, 920, 56, C["surface"], 12, C["border"]))
    b.append(text(52, 211, "古典音乐会 · 秋夜（已结束）", 13, C["text"], 600))
    b.append(f'<path d="M310 207 l4 4 l4 -4" fill="none" stroke="{C["muted"]}" stroke-width="1.5"/>')
    b.append(line(352, 192, 352, 220, C["border"]))
    b.append(text(372, 211, "全部场次", 12, C["sub"]))
    b.append(f'<path d="M440 207 l4 4 l4 -4" fill="none" stroke="{C["muted"]}" stroke-width="1.5"/>')
    b.append(text(556, 211, "按活动统计", 12, C["primary"], 600))
    b.append(text(650, 211, "按场次统计", 12, C["sub"]))
    b.append(button(1172, 188, 164, 36, "导出名单", "primary", 12))
    stats = [("报名人数", "96", C["text"]), ("出席率", "91%", C["success"]), ("退票率", "3.1%", C["warning"]), ("候补递补", "18", C["primary"])]
    for i, (label, value, color) in enumerate(stats):
        x = 32 + i * 236
        b.append(rect(x, 250, 212, 74, C["surface"], 12, C["border"]))
        b.append(text(x + 16, 278, label, 11, C["muted"]))
        b.append(text(x + 16, 306, value, 22, color, 700))
    b.append(rect(32, 340, 920, 440, C["surface"], 16, C["border"]))
    for x, label in [(56, "姓名"), (236, "场次"), (356, "票种"), (500, "状态"), (650, "手机号")]:
        b.append(text(x, 374, label, 11, C["muted"], 500))
    b.append(line(56, 388, 928, 388))
    rows = [
        ("林同学", "11月16日 19:30", "VIP 票", "已检票", "138****8888"),
        ("周雨", "11月16日 19:30", "普通票", "已检票", "139****6120"),
        ("陈默", "11月16日 19:30", "普通票", "未检票", "137****3091"),
        ("许知", "11月16日 19:30", "普通票", "自行取消", "186****7723"),
    ]
    for i, (name, session, ticket, status, phone) in enumerate(rows):
        y = 412 + i * 82
        b.append(text(56, y + 24, name, 13, C["text"], 600))
        b.append(text(236, y + 24, session, 11, C["sub"]))
        b.append(text(356, y + 24, ticket, 11, C["sub"]))
        color = C["success"] if status == "已检票" else (C["danger"] if status in ["未检票", "自行取消"] else C["primary"])
        b.append(badge(500, y + 8, status, color, C["success_bg"] if color == C["success"] else C["danger_bg"] if color == C["danger"] else C["blue_tint"], 10))
        b.append(text(650, y + 24, phone, 11, C["sub"]))
        b.append(line(56, y + 56, 928, y + 56, C["border"]))
    b.append(rect(976, 178, 432, 620, C["surface"], 16, C["border"]))
    b.append(text(1000, 216, "导出与权限", 18, C["text"], 700))
    notes = [
        ("导出字段", "姓名、场次、票种；不含完整手机号"),
        ("手机号可见性", "组织者只看到遮挡版；完整版仅管理员与本人"),
        ("统计口径", "全部场次结束后开放；已取消/候补不计入"),
        ("名单范围", "仅本活动组织者与管理员可见"),
    ]
    for i, (t, d) in enumerate(notes):
        y = 258 + i * 94
        b.append(text(1000, y, t, 13, C["text"], 600))
        b.append(text(1000, y + 24, d, 11, C["sub"]))
    b.append(rect(1000, 690, 384, 64, C["blue_tint"], 10))
    b.append(text(1016, 714, "当前活动已全部结束，统计已开放。", 11, C["primary"], 600))
    b.append(text(1016, 734, "导出名单不包含完整手机号。", 11, C["sub"]))
    return svg_doc("".join(b), defs_gradient())


def screen_admin_review():
    b = [rect(0, 0, W, H, C["bg"]), top_nav("审核处置", "管理员", name="王管理", avatar="王", items=[("审核处置", 220), ("全平台数据", 320), ("审计", 430)])]
    b.append(text(32, 126, "审核与处置", 30, C["text"], 700))
    b.append(text(32, 154, "审核活动、处理举报、账号与报名处置", 14, C["sub"]))
    for i, (label, active) in enumerate([("活动审核", True), ("举报处理", False), ("账号与处置", False)]):
        x = 32 + i * 118
        b.append(text(x, 195, label, 13, C["primary"] if active else C["sub"], 600 if active else 400))
        if active:
            b.append(rect(x, 204, 60, 3, C["primary"], 2))
    b.append(rect(32, 230, 400, 620, C["surface"], 16, C["border"]))
    b.append(text(56, 270, "待审核活动 3", 16, C["text"], 700))
    items = [("城市音乐节 · 夏日专场", "发布审核 · 组织者 李晨", "11-01 09:30", True), ("沉浸式戏剧《夜航》", "修改审核 · 组织者 李晨", "10-31 18:20", False), ("设计沙龙：AI 与创作", "取消申请 · 组织者 周舟", "10-31 16:10", False)]
    for i, (title, meta, time, selected) in enumerate(items):
        y = 296 + i * 92
        b.append(rect(48, y, 368, 76, C["blue_tint"] if selected else C["surface"], 10, C["primary"] if selected else C["border"]))
        b.append(text(64, y + 28, title, 13, C["text"], 600))
        b.append(text(64, y + 48, meta, 10, C["sub"]))
        b.append(text(64, y + 66, time, 10, C["muted"]))
    b.append(rect(452, 230, 956, 620, C["surface"], 16, C["border"]))
    b.append(text(476, 270, "城市音乐节 · 夏日专场", 20, C["text"], 700))
    b.append(badge(1310, 252, "待审核", C["warning"], C["warning_bg"], 10))
    b.append(text(476, 296, "组织者：李晨 · 提交于 11-01 09:30 · 审核时限：一周内", 11, C["sub"]))
    b.append(text(476, 336, "本次提交的变更", 14, C["text"], 700))
    b.append(rect(476, 352, 908, 128, C["bg"], 10))
    for i, (field, before, after) in enumerate([("活动时间", "11月8日 19:30", "11月9日 19:30"), ("活动地点", "新庄国展中心", "南京奥体中心"), ("容量 / 票价", "无变化", "无变化")]):
        y = 380 + i * 30
        b.append(text(496, y, field, 11, C["muted"]))
        b.append(text(600, y, before, 11, C["sub"]))
        b.append(text(800, y, "→", 11, C["muted"]))
        b.append(text(830, y, after, 11, C["text"], 500))
    b.append(text(476, 518, "组织者说明", 12, C["text"], 600))
    b.append(text(476, 540, "因场地调整，申请把活动时间与地点改到 11 月 9 日南京奥体中心，容量和票价不变。", 11, C["sub"]))
    b.append(text(476, 584, "审核意见", 12, C["text"], 600))
    b.append(rect(476, 598, 908, 74, C["bg"], 10, C["border"]))
    b.append(text(492, 624, "填写通过/驳回原因（会通知组织者）", 11, C["muted"]))
    b.append(button(1120, 692, 120, 38, "驳回", "secondary", 12))
    b.append(button(1252, 692, 132, 38, "通过", "primary", 12))
    b.append(line(476, 754, 1408, 754))
    b.append(text(476, 782, "其他处置", 12, C["text"], 700))
    for i, label in enumerate(["举报处理", "封禁账号", "强制退票", "创建检票账号"]):
        b.append(button(476 + i * 176, 800, 160, 32, label, "ghost", 11))
    return svg_doc("".join(b), defs_gradient())


def screen_inspector():
    b = [rect(0, 0, W, H, C["bg"]), top_nav("检票工作台", "检票员", name="赵敏", avatar="赵", items=[("检票工作台", 220), ("负责活动", 330)])]
    b.append(text(32, 126, "检票工作台", 30, C["text"], 700))
    b.append(text(32, 154, "只显示你负责的活动和检票请求", 14, C["sub"]))
    b.append(rect(32, 178, 1376, 80, C["surface"], 14, C["border"]))
    b.append(text(56, 210, "城市音乐节 · 夏日专场", 17, C["text"], 700))
    b.append(text(56, 234, "11月8日 19:30 · 新庄国展中心", 11, C["sub"]))
    b.append(text(500, 210, "检票开放 18:30–21:00", 12, C["sub"]))
    b.append(badge(1260, 196, "检票中", C["success"], C["success_bg"], 10))
    b.append(text(1260, 236, "已处理 23 · 待处理 5", 10, C["muted"]))
    b.append(rect(32, 286, 520, 520, C["surface"], 16, C["border"]))
    b.append(text(56, 326, "待处理请求 5", 16, C["text"], 700))
    reqs = [("#CK-1024", "林**", "普通票", "19:02", True), ("#CK-1025", "周**", "VIP 票", "19:03", False), ("#CK-1026", "陈**", "普通票", "19:05", False), ("#CK-1027", "许**", "普通票", "19:07", False)]
    for i, (no, name, ticket, time, selected) in enumerate(reqs):
        y = 350 + i * 82
        b.append(rect(48, y, 488, 68, C["blue_tint"] if selected else C["surface"], 10, C["primary"] if selected else C["border"]))
        b.append(text(64, y + 26, no, 13, C["text"], 600))
        b.append(text(64, y + 48, f"{name} · {ticket} · {time}", 10, C["sub"]))
        b.append(badge(430, y + 8, "待处理", C["warning"], C["warning_bg"], 9))
    b.append(rect(572, 286, 836, 520, C["surface"], 16, C["border"]))
    b.append(text(596, 326, "请求 #CK-1024", 20, C["text"], 700))
    b.append(badge(1300, 308, "待处理", C["warning"], C["warning_bg"], 10))
    b.append(text(596, 362, "参与者：林**（遮挡） · 普通票 · 请求时间 19:02", 12, C["sub"]))
    b.append(rect(596, 386, 788, 92, C["bg"], 10))
    b.append(text(616, 416, "报名记录：已购票", 12, C["text"], 600))
    b.append(text(616, 440, "场次：11月8日 19:30 · 检票开放时间：18:30–21:00", 11, C["sub"]))
    b.append(text(616, 460, "仅显示请求编号与遮挡姓名，不显示完整名单/手机号", 11, C["muted"]))
    b.append(text(596, 518, "处理结果", 13, C["text"], 700))
    b.append(button(596, 540, 170, 42, "通过检票", "primary", 13))
    b.append(button(784, 540, 170, 42, "标记异常", "secondary", 13))
    b.append(text(596, 614, "凭证不符时标记异常，不通过；不能直接修改报名状态。", 11, C["sub"]))
    b.append(rect(596, 650, 788, 120, C["blue_tint"], 10))
    b.append(text(616, 680, "岗位约束", 11, C["primary"], 700))
    b.append(text(616, 704, "只能处理自己负责活动的检票请求；不能访问完整名单；不能查看完整手机号。", 11, C["sub"]))
    b.append(text(616, 726, "重复检票只有第一次有效，后续提示“已检票”，不禁止入场。", 11, C["sub"]))
    return svg_doc("".join(b), defs_gradient())


def screen_audit():
    b = [rect(0, 0, W, H, C["bg"]), top_nav("审计", "管理员", name="王管理", avatar="王", items=[("审核处置", 220), ("全平台数据", 320), ("审计", 430)])]
    b.append(text(32, 126, "审计日志", 30, C["text"], 700))
    b.append(text(32, 154, "保存至少 6 个月；按角色可见范围查询关键操作留痕", 14, C["sub"]))
    b.append(rect(32, 178, 1376, 56, C["surface"], 12, C["border"]))
    for x, label, chev in [(52, "对象类型", 72), (226, "操作类型", 72), (400, "操作人", 60), (544, "时间范围", 72), (712, "关键词", 0)]:
        b.append(text(x, 211, label, 11, C["sub"]))
        if chev:
            b.append(f'<path d="M{x+chev} 207 l4 4 l4 -4" fill="none" stroke="{C["muted"]}" stroke-width="1.5"/>')
    b.append(line(880, 192, 880, 220, C["border"]))
    b.append(text(912, 211, "全部对象 / 操作 / 操作人，按时间倒序", 11, C["muted"]))
    b.append(rect(32, 264, 1000, 520, C["surface"], 16, C["border"]))
    for x, label in [(56, "时间"), (196, "操作人"), (316, "对象"), (500, "操作"), (660, "前后状态")]:
        b.append(text(x, 302, label, 11, C["muted"], 500))
    b.append(line(56, 316, 1008, 316))
    rows = [
        ("11-01 14:22", "王管理", "活动 #A102", "审核通过", "待审核 → 公开"),
        ("11-01 13:50", "李晨", "活动 #A102", "修改时间/地点", "公开 → 待审核"),
        ("11-01 12:08", "林同学", "报名 #R208", "报名成功", "无 → 已购票"),
        ("11-01 11:34", "赵敏", "检票请求 #CK-1024", "检票通过", "待处理 → 通过"),
        ("10-31 18:12", "王管理", "账号 #U33", "封禁账号", "正常 → 封禁"),
    ]
    for i, (time, operator, obj, action, state) in enumerate(rows):
        y = 344 + i * 80
        b.append(text(56, y + 22, time, 11, C["sub"]))
        b.append(text(196, y + 22, operator, 11, C["text"], 500))
        b.append(text(316, y + 22, obj, 11, C["sub"]))
        b.append(text(500, y + 22, action, 11, C["text"], 500))
        b.append(text(660, y + 22, state, 11, C["sub"]))
        b.append(line(56, y + 56, 1008, y + 56, C["border"]))
    b.append(rect(1052, 264, 356, 520, C["surface"], 16, C["border"]))
    b.append(text(1076, 304, "留痕详情", 18, C["text"], 700))
    details = [("操作人", "王管理（管理员）"), ("操作时间", "2026-11-01 14:22"), ("对象", "活动 #A102"), ("操作", "审核通过"), ("前状态", "待审核"), ("后状态", "公开"), ("说明", "审核通过，活动公开，通知组织者")]
    for i, (k, v) in enumerate(details):
        y = 342 + i * 44
        b.append(text(1076, y, k, 11, C["muted"]))
        b.append(text(1160, y, v, 11, C["text"], 500))
    b.append(rect(1076, 680, 308, 72, C["blue_tint"], 10))
    b.append(text(1092, 706, "权限提示", 11, C["primary"], 700))
    b.append(text(1092, 726, "管理员可看全部；其他角色按对象/角色可见", 10, C["sub"]))
    return svg_doc("".join(b), defs_gradient())


def defs_gradient():
    return ('<linearGradient id="g1" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#2563EB"/><stop offset="100%" stop-color="#7C3AED"/></linearGradient>'
            '<linearGradient id="g2" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#0D9488"/><stop offset="100%" stop-color="#0F766E"/></linearGradient>'
            '<linearGradient id="g3" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#EA580C"/><stop offset="100%" stop-color="#F59E0B"/></linearGradient>'
            '<linearGradient id="g4" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#475569"/><stop offset="100%" stop-color="#7C3AED"/></linearGradient>')


if __name__ == "__main__":
    out = Path(__file__).parent
    screens = {
        "01_登录注册": screen_login,
        "02_活动浏览与详情": screen_activity,
        "03_报名购票与候补": screen_checkout,
        "04_我的票与退票": screen_my_tickets,
        "05_组织者活动管理": screen_organizer_activities,
        "06_组织者名单与统计": screen_organizer_roster,
        "07_管理员审核与处置": screen_admin_review,
        "08_检票员工作台": screen_inspector,
        "09_审计日志与权限": screen_audit,
    }
    for name, fn in screens.items():
        (out / f"{name}.svg").write_text(fn(), encoding="utf-8")
    print("written", len(screens), "svg")
