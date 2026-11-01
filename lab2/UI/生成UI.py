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
    b.append(lines(56, 296, ["让每一场活动", "都顺利发生"], 40, "#FFFFFF", 700, 52))
    b.append(text(56, 392, "活动发布 · 报名购票 · 候补递补 · 检票管理", 15, "#DBEAFE", 400))
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
    b.append(text(730, 232, "注册", 16, C["muted"], 500))
    b.append(input_box(672, 304, 336, 48, "请输入手机号", "手机号", icon=icon_person))
    b.append(input_box(672, 390, 336, 48, "请输入密码", "密码"))
    b.append(f'<path d="M972 414 c6 -9 22 -9 28 0 c-6 9 -22 9 -28 0z" fill="none" stroke="{C["muted"]}" stroke-width="1.6"/><circle cx="986" cy="414" r="3" fill="{C["muted"]}"/>')
    b.append(rect(672, 462, 14, 14, C["surface"], 3, C["border"]))
    b.append(text(694, 474, "记住我", 12, C["sub"]))
    b.append(text(1008, 474, "忘记密码？无自助找回", 12, C["muted"], 400, "end"))
    b.append(button(672, 494, 336, 48, "登录", "primary"))
    b.append(line(672, 568, 1008, 568, C["border"]))
    b.append(text(672, 598, "还没有账号？", 12, C["muted"]))
    b.append(text(762, 598, "注册新账号", 12, C["primary"], 600))
    b.append(text(672, 618, "管理员、检票员账号由平台创建，不开放自助注册", 11, C["muted"]))

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


if __name__ == "__main__":
    out = Path(__file__).parent
    (out / "01_登录注册.svg").write_text(screen_login(), encoding="utf-8")
    print("written", out / "01_登录注册.svg")


def top_nav(active="活动", role="参与者", name="林同学", breadcrumb=None):
    b = [rect(0, 0, W, 72, C["surface"]), line(0, 72, W, 72, C["border"])]
    b.append(rect(32, 19, 34, 34, C["primary"], 9))
    b.append(f'<path d="M41 28 h16 v16 h-16 z" fill="none" stroke="#FFFFFF" stroke-width="1.6"/>'
             f'<path d="M46 28 v16 M52 28 v16" stroke="#FFFFFF" stroke-width="1.2" stroke-dasharray="2 2"/>')
    b.append(text(78, 43, "活动票务", 18, C["text"], 700))
    if breadcrumb:
        b.append(text(210, 43, breadcrumb, 12, C["muted"]))
    else:
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
    b.append(text(1288, 41, "林", 13, C["primary_dark"], 700, "middle"))
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
    b.append(line(512, 192, 512, 220, C["border"]))
    for i, (label, active) in enumerate([("全部", True), ("音乐", False), ("戏剧", False), ("运动", False), ("讲座", False)]):
        x = 532 + i * 64
        if active:
            b.append(rect(x, 195, 48, 24, C["primary"], 12))
            b.append(text(x + 24, 211, label, 11, "#FFFFFF", 600, "middle"))
        else:
            b.append(text(x + 18, 211, label, 11, C["sub"], 400, "middle"))
    b.append(line(900, 192, 900, 220, C["border"]))
    for x, label in [(920, "时间范围"), (1060, "全部状态"), (1200, "最新发布")]:
        b.append(text(x, 211, label, 11, C["sub"]))
        b.append(f'<path d="M{x+72} 207 l4 4 l4 -4" fill="none" stroke="{C["muted"]}" stroke-width="1.5"/>')

    cards = [
        ("城市音乐节 · 夏日专场", "11月8日 19:30 · 南京 · 新庄国展中心", "音乐 / 户外", "¥120 起", "余 36", "售票中", C["success"], C["success_bg"], "g1", "乐", True),
        ("沉浸式戏剧《夜航》", "11月12日 19:30 · 南京 · 鼓楼剧场", "戏剧 / 沉浸式", "¥180 起", "余 12", "即将售罄", C["warning"], C["warning_bg"], "g2", "剧", False),
        ("校园马拉松志愿者", "11月16日 08:00 · 南京 · 仙林校区", "运动 / 公益", "免费", "余 80", "报名中", C["primary"], C["blue_tint"], "g3", "跑", False),
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
    b.append(text(56, 542, "报名信息", 15, C["text"], 700))
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
    b.append(text(72, 758, "候补期间可取消并全额退款；候补成功不等于最终买到票。", 11, C["muted"]))
    b.append(button(56, 790, 776, 44, "加入候补并支付标记", "primary", 14))
    b.append(text(444, 852, "返回活动详情", 11, C["primary"], 500, "middle"))
    b.append(rect(876, 220, 532, 620, C["surface"], 16, C["border"]))
    b.append(text(900, 258, "候补说明", 18, C["text"], 700))
    b.append(text(900, 282, "按票种排队，先到先得", 12, C["sub"]))
    steps = [("1", "加入候补队列", "记录入队时间，排队顺序公开"), ("2", "等待名额释放", "有人退票后，按队首顺序递补"), ("3", "递补或退款", "递补成功生成已购票；未成功全额退款")]
    for i, (num, title, desc) in enumerate(steps):
        y = 326 + i * 92
        b.append(circle(920, y, 13, C["blue_tint"]))
        b.append(text(920, y + 4, num, 12, C["primary"], 700, "middle"))
        b.append(text(946, y + 4, title, 14, C["text"], 600))
        b.append(text(946, y + 26, desc, 11, C["sub"]))
        if i < 2:
            b.append(line(920, y + 15, 920, y + 77, C["border"], 1, "4 4"))
    b.append(rect(900, 598, 484, 72, C["bg"], 10))
    b.append(text(918, 624, "当前候补人数", 11, C["muted"]))
    b.append(text(918, 650, "12 人", 20, C["text"], 700))
    b.append(text(1040, 624, "预计等待", 11, C["muted"]))
    b.append(text(1040, 650, "以实际递补为准", 13, C["sub"], 500))
    b.append(text(900, 708, "有票时怎么办？", 13, C["text"], 700))
    b.append(text(900, 730, "若其他票种仍有余票，可直接选择有票票种报名，无需候补。", 11, C["sub"]))
    b.append(rect(900, 752, 484, 64, C["blue_tint"], 10))
    b.append(text(918, 776, "提示", 11, C["primary"], 700))
    b.append(text(918, 796, "候补记录独立于报名记录；递补成功才生成“已购票”报名记录。", 11, C["sub"]))
    return svg_doc("".join(b), defs)


if __name__ == "__main__":
    out = Path(__file__).parent
    (out / "01_登录注册.svg").write_text(screen_login(), encoding="utf-8")
    (out / "02_活动浏览与详情.svg").write_text(screen_activity(), encoding="utf-8")
    (out / "03_报名购票与候补.svg").write_text(screen_checkout(), encoding="utf-8")
    print("written 3 svg")
