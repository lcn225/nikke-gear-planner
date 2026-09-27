# test_new_functions.py
#
# 冒烟测试。刻意只用 printf + assert，不引 pytest —— 仓库没有测试框架，
# 加一个依赖不值得。运行：
#     python3 test/test_new_functions.py

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import HARD_ANIM_SEC, INSTANT_CHARGE_LINE
from engine.damage_model import (
    CharSummary,
    build_char_summary,
    compute_m_ammo,
    compute_m_cs,
    compute_relative_gain,
    get_profile,
)
from engine.probability import expected_cost_to_achieve_targets

EPS = 1e-9

# 真实名册属个人数据，不入库（见 .gitignore）。下面三条测试钉的是**这份名册**的
# 具体数字（52 角色 / 112 T10 / 247 词条），缺了就大声跳过 —— 不换成
# input/cn_collect.sample.json：样例数字对不上，换过去只会变成一串看不懂的
# 断言失败，比直接说「缺文件」更难排查。放一份自己的名册即可恢复这三条。
_OWN_ROSTER = Path(__file__).resolve().parent.parent / "input" / "cn_collect.json"
_NEEDS_OWN_ROSTER = {"test_roster_loader", "test_tier_weighting", "test_character_ladder"}

# 下面这条测试钉的是**快照生成侧**的行为（别名表能否解释全部语料写法），
# 它依赖的工具不在仓库里。缺工具就大声跳过 —— 不删掉：在本机保留一份即可
# 继续跑，而新克隆者看到的是「为什么没跑」而不是「假装通过」。
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SNAPSHOT_TOOLING_MARKERS = [_REPO_ROOT / "verify_alias_coverage.py"]
_NEEDS_SNAPSHOT_TOOLING = {"test_alias_coverage"}


def test_physical_config():
    """物理参数这条必须与手工推导值一致（上游改数值时这里最先响）。"""
    p = get_profile("爱丽丝")
    assert p is not None, "爱丽丝没有物理数据"

    assert p.base_ammo == 6, p.base_ammo
    assert p.fire_rate == 1.0, p.fire_rate
    assert p.reload_time == 2.0, p.reload_time

    # 蓄力推导：charge_time ×(1 − 技能蓄速) + 硬直 = 1.5 ×(1−0.9182) + 0.35
    assert p.charge_time == 1.5, p.charge_time
    assert abs(p.base_time - 0.4727) < 1e-9, p.base_time
    assert abs(p.cs_threshold - 0.077) < 1e-9, p.cs_threshold

    print(f"爱丽丝: 弹夹={p.base_ammo}, 射速={p.fire_rate}, "
          f"蓄力时间={p.charge_time}s, base_time={p.base_time}, 秒蓄门槛={p.cs_threshold}")


def test_cs_multiplier():
    """蓄速乘区：未达门槛时线性，达门槛后封顶。"""
    p = get_profile("爱丽丝")

    m0 = compute_m_cs(0.0, p)
    # cs=0 时单发时间就是 base_time
    assert abs(m0 - 1.0 / p.base_time) < EPS, m0

    # 刚好到门槛
    m_at = compute_m_cs(p.cs_threshold, p)
    # 超过门槛不再增长
    assert abs(compute_m_cs(p.cs_threshold + 0.5, p) - m_at) < EPS, "越过秒蓄门槛后不该继续增长"

    # 单发时间不得低于硬直动画
    assert 1.0 / m_at >= HARD_ANIM_SEC - EPS, "单发时间低于硬直动画地板"

    # 非蓄力角色恒为 1.0
    for name in ["娜嘉", "德雷克", "皇冠"]:
        q = get_profile(name)
        assert q.base_time is None, f"{name} 不该有 base_time"
        assert compute_m_cs(0.2, q) == 1.0, f"{name} 蓄速乘区应为 1.0"

    print(f"蓄速乘区: m(0)={m0:.6f}, m(门槛)={m_at:.6f}, 增益={(m_at/m0-1)*100:.2f}%")


def test_ammo_multiplier():
    """装弹乘区由角色自己的 base_ammo / fire_rate / reload_time 决定。"""
    p = get_profile("爱丽丝")
    assert abs(compute_m_ammo(0.0, p) - 0.75) < EPS, compute_m_ammo(0.0, p)

    # 反装弹角色：装弹收益反向
    q = get_profile("阿妮斯：闪耀夏日")
    assert q.anti_ammo is True, "阿妮斯：闪耀夏日 应为反装弹角色"
    assert compute_m_ammo(0.5, q) < compute_m_ammo(0.0, q), "反装弹角色的装弹乘区应随装弹下降"

    print(f"装弹乘区: 爱丽丝 m(0)={compute_m_ammo(0.0, p):.4f}, "
          f"阿妮斯(反装弹) m(0)={compute_m_ammo(0.0, q):.4f} m(0.5)={compute_m_ammo(0.5, q):.4f}")


def test_expected_cost():
    cost = expected_cost_to_achieve_targets([], {"蓄力速度", "优越代码"})
    assert cost > 0, cost
    print(f"洗出蓄速+优越的期望成本: {cost:.2f} 石")


def test_damage_model():
    """模拟爱丽丝当前状态：一条 4.92% 蓄速的收益。"""
    p = get_profile("爱丽丝")
    before = CharSummary(atk_pct=0.0, ele_pct=0.0, ammo_pct=0.0, cs_pct=0.0)
    after = CharSummary(atk_pct=0.0, ele_pct=0.0, ammo_pct=0.0, cs_pct=0.0492)
    gain = compute_relative_gain(before, after, p)
    assert abs(gain - 0.185009) < 1e-5, gain
    print(f"单条蓄速(4.92%)收益: {gain*100:.4f}%")


def test_build_char_summary():
    """从装备构建乘区快照。用真实槽位名（上游口径）。"""
    class _Line:
        def __init__(self, buff_type, tier, value_pct):
            self.buff_type, self.tier, self.value_pct = buff_type, tier, value_pct

        @property
        def is_empty(self):
            return self.buff_type == "" or self.tier == 0

    class _Gear:
        def __init__(self, lines, slot="头"):
            self.lines = lines
            self.slot = slot

    gears = {
        "头": _Gear([_Line("攻击力增加", 11, 11.81), _Line("", 0, 0.0), _Line("", 0, 0.0)]),
        "甲": _Gear([_Line("优越代码伤害增加", 13, 26.36), _Line("", 0, 0.0), _Line("", 0, 0.0)]),
    }
    s = build_char_summary(gears)
    assert abs(s.atk_pct - 0.1181) < EPS, s.atk_pct
    assert abs(s.ele_pct - 0.2636) < EPS, s.ele_pct
    assert s.ammo_pct == 0.0 and s.cs_pct == 0.0

    # 合法但未建模的词条（防御力增加）应被静默跳过，不计入任何乘区
    gears["脚"] = _Gear([_Line("防御力增加", 9, 10.40), _Line("", 0, 0.0), _Line("", 0, 0.0)])
    s2 = build_char_summary(gears)
    assert s2.atk_pct == s.atk_pct and s2.ele_pct == s.ele_pct

    # 非标准名（旧写法）必须抛错，不能静默算成 0
    gears["脚"] = _Gear([_Line("攻刃", 11, 11.81), _Line("", 0, 0.0), _Line("", 0, 0.0)])
    try:
        build_char_summary(gears)
    except KeyError:
        pass
    else:
        raise AssertionError("非标准词条名应当抛 KeyError，而不是静默跳过")

    print(f"乘区快照: 攻击={s.atk_pct:.4f} 优越={s.ele_pct:.4f}（防御力未建模已跳过，旧名已拒绝）")


def test_roster_loader():
    """
    上游名册读入。逐项对齐 input/数据说明.md 里写死的数字 ——
    那些数字是文档作者人工数出来的，对不上就说明读法跑偏了。
    """
    from engine.roster_loader import load_roster

    r = load_roster("input/cn_collect.json")

    # 52 角色 / 208 槽 = 112 T10 + 96 T9 / 247 条真实词条 + 89 个「未获得效果」
    assert len(r.characters) == 52, len(r.characters)
    assert r.t10_slots == 112, r.t10_slots
    assert r.t9_slots == 96, r.t9_slots
    assert r.buff_lines == 247, r.buff_lines
    assert r.empty_placeholders == 89, r.empty_placeholders
    assert r.skipped == [], r.skipped

    # 小数 → 百分比 + 档位反查：上游 0.1181 = 11.81% = Tier 11
    alice = next(c for c in r.characters if c.name == "爱丽丝")
    head = alice.gears["头"].lines
    assert head[0].buff_type == "攻击力增加" and head[0].tier == 10, head[0]
    assert abs(head[0].value_pct - 11.11) < 1e-9, head[0].value_pct
    assert head[2].tier == 11 and abs(head[2].value_pct - 11.81) < 1e-9, head[2]

    # 词条位不是顺序填充（XEX 形态 21 个槽）—— 爱丽丝 脚 是 [有, 有, 空]
    foot = alice.gears["脚"].lines
    assert foot[0].buff_type == "暴击率增加" and foot[1].buff_type == "蓄力伤害增加"
    assert foot[2].is_empty

    # T9 整槽 → 3 个空槽，不是「T10 但没词条」
    queen = next(c for c in r.characters if c.name == "QUEEN（真）")
    assert queen.gears["甲"].empty_slot_count() == 3, queen.gears["甲"]
    assert queen.gears["甲"].lines[0].buff_type == ""

    # 「未获得效果」占位符 → 空槽（它是 T10 的证据，但不占词条）
    drake = next(c for c in r.characters if c.name == "德雷克")
    assert drake.gears["头"].lines[1].is_empty, drake.gears["头"].lines[1]
    assert drake.gears["头"].count_buff("攻击力增加") == 1

    # 当前这份上游数据是干净的（0 处异常）。
    # 曾经的「白雪公主 头第2条 数值为 null」已于 2026-09-25 被上游补齐 ——
    # 这正是「留空 + 报警，重抓自愈」政策预期的结果。脏数据的**处理逻辑**
    # 由下面的合成用例守住，不依赖真实数据恰好脏着。
    assert r.issues == [], r.issues

    # 没接推荐表 → 不编造默认目标（targets 为 None），且如实在报告里标出来
    assert r.targets_attached is False
    assert all(c.targets is None for c in r.characters)
    assert "目标词条未接入" in r.format_report()

    print(f"名册: {len(r.characters)} 角色 / {r.t10_slots} T10 + {r.t9_slots} T9 / "
          f"{r.buff_lines} 条词条 / {len(r.issues)} 处异常")


def test_roster_dirty_data_handling():
    """
    脏数据的处理逻辑。**用合成输入，不依赖真实数据恰好脏着** ——
    上游修好之后（2026-09-25 就把白雪公主那条补上了），
    如果测试还挂在真实数据上，这条逻辑就再也没人守了。

    三种空态必须分开：
      整槽三条名称全 null        → T9（没有改造词条，属预期）
      「未获得效果」             → T10 的空词条位（它是 T10 的证据）
      有名称但数值为 null        → 脏数据，留空 + 报警，不猜档位
    """
    from engine.roster_loader import parse_roster

    fake = {"角色": [{
        "姓名": "测试角色", "战力": 1,
        # T10：第 1 条有名称无数值（脏），另两条是空占位
        "头": {"等级": 3, "词条": [
            {"名称": "攻击力增加", "数值": None},
            {"名称": "未获得效果", "数值": 0},
            {"名称": "未获得效果", "数值": 0}]},
        # T9：三条名称全 null，等级也是 null
        "甲": {"等级": None, "词条": [{"名称": None, "数值": None}] * 3},
        # T10：三条全空位（一件空装备，但它是 T10）
        "手": {"等级": 0, "词条": [{"名称": "未获得效果", "数值": 0}] * 3},
        # T10：一条真词条，数值合法
        "脚": {"等级": 1, "词条": [
            {"名称": "攻击力增加", "数值": 0.1181},
            {"名称": "未获得效果", "数值": 0},
            {"名称": "未获得效果", "数值": 0}]},
    }]}

    res = parse_roster(fake)
    c = res.characters[0]

    # 空态分开：甲是 T9，其余三件是 T10
    assert res.t9_slots == 1 and res.t10_slots == 3, (res.t9_slots, res.t10_slots)
    # T9 槽上游等级为 null → 按 Lv0 起算，但要计数报警
    assert res.t9_level_unknown == 1
    assert c.gears["甲"].level == 0
    assert c.gears["甲"].empty_slot_count() == 3

    # 「未获得效果」不占词条：只有脚那条真词条算数
    assert res.buff_lines == 1, res.buff_lines
    # 空占位 = 头 2 + 手 3 + 脚 2 = 7；甲是 T9，整槽不算占位
    assert res.empty_placeholders == 7, res.empty_placeholders
    assert c.gears["脚"].lines[0].tier == 11, c.gears["脚"].lines[0]

    # 有名称无数值 → 留空 + 报警，不猜档位
    assert len(res.issues) == 1, res.issues
    issue = res.issues[0]
    assert (issue.character, issue.slot, issue.line_index) == ("测试角色", "头", 0), issue
    assert issue.kind == "缺数值", issue.kind
    assert c.gears["头"].lines[0].is_empty, "脏数据条应留空，不能猜一个档位填上"

    # 非标准词条名必须抛错（命名铁律），不能静默跳过
    bad = {"角色": [dict(fake["角色"][0], 头={"等级": 0, "词条": [
        {"名称": "攻刃", "数值": 0.1181},
        {"名称": "未获得效果", "数值": 0},
        {"名称": "未获得效果", "数值": 0}]})]}
    try:
        parse_roster(bad)
    except KeyError:
        pass
    else:
        raise AssertionError("非标准词条名应当抛 KeyError")

    print(f"脏数据: 留空+报警 1 处 | T9/T10 分开 | 空占位 {res.empty_placeholders} | "
          f"非标准名已拒绝")


def test_targets_snapshot():
    """
    推荐表快照。钉的是**随仓库分发出去的那份数据**本身：

    1. **快照是齐的。** 201 个角色、每个 mode 的结构与字段都在 —— 数据文件被
       误截断/误替换时立刻响，而不是等到某个目标词条凭空消失、ROI 悄悄算偏。
    2. **手工核对的角色逐条断言。** 覆盖主副分层、阈值 vs 件数、互斥组、
       相邻词条名拼接、反装弹角色。

    解析器本身不在仓库内，所以这里不再重跑它，
    只校验它**当时产出的快照**。想连解析一起回归，在本机保留脚本后跑
    test_alias_coverage 那套。
    """
    repo = Path(__file__).resolve().parent.parent
    parsed = json.loads((repo / "data/targets_parsed.json").read_text(encoding="utf-8"))
    ch = parsed["characters"]

    # ── 防线 1：快照完整性 ──
    assert len(ch) == 201, f"推荐表角色数应为 201，实际 {len(ch)}"
    for name, c in ch.items():
        assert c.get("modes"), f"{name} 没有任何 mode"
        for mode, mt in c["modes"].items():
            for key in ("primary", "secondary"):
                assert key in mt, f"{name}/{mode} 缺 {key}"
                assert isinstance(mt[key], list), f"{name}/{mode}/{key} 不是列表"

    def got(name, mode, field):
        mt = ch[name]["modes"][mode]
        key = {"core": "primary", "optional": "secondary"}[field]
        return {e["buff"]: (e["count"], e["count_kind"]) for e in mt[key]}

    # ── 防线 2：手工核对 ──
    # 爱丽丝：core 四件全是 exact，面板四项齐全
    a = got("爱丽丝", "PVE", "core")
    assert a["优越代码伤害增加"] == (4, "exact"), a
    assert a["蓄力速度增加"] == (2, "exact"), a
    assert {p["buff"]: p["total_pct"] for p in ch["爱丽丝"]["modes"]["PVE"]["panel"]} == {
        "优越代码伤害增加": 80.0, "攻击力增加": 40.0,
        "最大装弹数增加": 180.0, "蓄力速度增加": 8.5}

    # 皇冠：core 是「至少2条」——阈值不是件数，别混成 exact
    c = got("皇冠", "PVE", "core")
    assert c["最大装弹数增加"] == (2, "at_least"), c
    # 主副分层：装弹在 core（主），优越/攻击在 optional（副）
    assert "优越代码伤害增加" not in c
    assert got("皇冠", "PVE", "optional")["优越代码伤害增加"] == (4, "exact")

    # 拉毗：括号后的「暴击任意 爆伤任意」必须还在（曾被右括号配对 bug 吞掉）
    r2 = got("拉毗", "PVE", "optional")
    assert r2["最大装弹数增加"] == (2, "at_least"), r2
    assert set(r2) == {"最大装弹数增加", "暴击率增加", "暴击伤害增加"}, r2

    # 海伦：`暴击/爆伤×4` 是互斥组，4 件是**整组的**配额，
    # 成员自身记为「没规定」——各挂 4 件会被读成 8 件
    h = got("海伦", "PVE", "optional")
    assert h["暴击率增加"] == (None, "unspecified"), h
    g = [g for g in ch["海伦"]["modes"]["PVE"]["groups"] if g["members"][0] == "暴击率增加"]
    assert g and g[0]["budget"] == 4, ch["海伦"]["modes"]["PVE"]["groups"]

    # 阿妮斯：反装弹角色，全部字段不得出现装弹（尾弹机制，装弹是负收益）
    for mode in ("PVE", "PVP"):
        mt = ch["阿妮斯：闪耀夏日"]["modes"][mode]
        assert not any("装弹" in e["buff"] for e in mt["primary"] + mt["secondary"]), mode
    # `暴击爆伤` 两个名字直接拼接，拆成双爆两条
    an = got("阿妮斯：闪耀夏日", "PVE", "optional")
    assert set(an) == {"暴击率增加", "暴击伤害增加"}, an

    # 德雷克：optional 是裸 `/` 组，按「任选」展开成全部候选
    dk = got("德雷克", "PVE", "optional")
    assert set(dk) == {"暴击率增加", "暴击伤害增加", "命中率增加"}, dk

    # 芙罗拉：只有 optional 跟随 pve，core 是自己的 —— 跟随是**逐字段**的，
    # 当成 mode 级属性会把 core 一起抹掉
    fp = ch["芙罗拉"]["modes"]["PVP"]
    assert fp["follow"] == {"optional": "PVE", "panel": "PVE"}, fp["follow"]
    assert len(fp["primary"]) == 3, fp["primary"]

    print(f"推荐表快照: {len(ch)} 角色 | primary "
          f"{sum(len(m['primary']) for c in ch.values() for m in c['modes'].values())} 条")


def test_tier_weighting():
    """
    跨角色折算：档位权重 + 主目标门禁。

    这两条是**排序正确性**的防线。它们的失效方式都是静默的 ——
    权重写错不会报错，只会让天梯悄悄排错；门禁失效则让副目标
    压过主目标。所以都用具体断言钉住。
    """
    from config import tier_weight, CG_WEIGHT, TIER_WEIGHT_Q
    from engine.roster_loader import load_roster_with_targets
    from engine.bidding_engine import GlobalBiddingEngine

    # ── 权重表 ──
    assert tier_weight("cg") == CG_WEIGHT == 0.0, "仓管权重必须是 0（不上场 = 收益为 0）"
    assert tier_weight("0") == 1.0
    # w = q^(2×tier)：T3 比 T1 低 q^4
    assert abs(tier_weight("3") / tier_weight("1") - TIER_WEIGHT_Q ** 4) < 1e-12
    # 单调递减：档位越差权重越低
    vals = [tier_weight(t) for t in ("0", "0.5", "1", "1.5", "2", "3")]
    assert vals == sorted(vals, reverse=True), vals
    # 未知/缺失档位不折算，也不猜
    assert tier_weight(None) == 1.0 and tier_weight("") == 1.0

    r = load_roster_with_targets()
    e = GlobalBiddingEngine(stones_held=300, credits_held=5_000_000)
    bids = e.run(r.characters)
    assert bids, "引擎没有产出任何竞价"

    # ── 排序分 = ROI × 权重 ──
    for b in bids:
        assert abs(b.sort_score - b.roi * b.tier_weight) < 1e-12 or b.equivalent_cost > 0
    assert all(bids[i].sort_score >= bids[i + 1].sort_score for i in range(len(bids) - 1)), \
        "天梯没有按排序分降序"

    # ── 仓管必须沉底 ──
    # 折算前露菲(tier=cg)能排到第 6，这是这个功能存在的理由。
    cg_best = min((b.priority for b in bids if b.tier == "cg"), default=None)
    n = len(bids)
    if cg_best is not None:
        assert cg_best > n * 0.9, f"仓管最高顺位 {cg_best}/{n}，没有被压下去"

    # ── 门禁：未达成 primary 的角色，其纯副目标候选必须标 ⏸ ──
    gated = [b for b in bids if b.gated]
    assert gated, "没有任何条目被门禁拦住，说明门禁没生效"
    for b in gated:
        unmet = e.unmet_primary.get(b.character_name)
        assert unmet, f"{b.character_name} 没有未达成的 primary 却被拦了"
        assert b.target_set, "开光/升级这类前置动作不该被门禁"
    # 反过来：已达成 primary 的角色不该有被拦的条目
    open_chars = {n for n, u in e.unmet_primary.items() if not u}
    assert not any(b.gated for b in bids if b.character_name in open_chars)

    print(f"折算: 仓管最高顺位 {cg_best}/{n} | 门禁拦住 {len(gated)} 条 | "
          f"q={TIER_WEIGHT_Q}")


def test_character_ladder():
    """
    角色培养榜：一角色一行、档位优先。

    这是主视图，排序错了整个工具就失去意义。断言钉住三件事：
    档位必须严格降序、每个角色只能占一行、已毕业的不出现在榜上。
    """
    from config import tier_rank
    from engine.roster_loader import load_roster_with_targets
    from engine.bidding_engine import (
        GlobalBiddingEngine, build_character_ladder, generate_character_ladder_report,
        character_rows_to_records, build_character_detail)

    from engine.data_loader import physical_skip_label

    r = load_roster_with_targets()
    e = GlobalBiddingEngine(stones_held=300, credits_held=5_000_000)
    bids = e.run(r.characters)
    # 与 main.py 的调用方式保持一致（含不可算角色的短标签）
    unavailable = {c.name: physical_skip_label(c.name) for c in r.characters}
    unavailable = {n: lbl for n, lbl in unavailable.items() if lbl}
    rows = build_character_ladder(
        r.characters, bids, e.unmet_primary, unavailable=unavailable)

    assert rows, "角色榜是空的"

    # 一角色一行
    names = [x.name for x in rows]
    assert len(names) == len(set(names)), "有角色占了不止一行"

    # 档位严格不降（tier_rank 越小越靠前）
    ranks = [tier_rank(x.tier) for x in rows]
    assert ranks == sorted(ranks), [
        (x.name, x.tier) for x in rows[:20]]

    # T0 未毕业的角色必须排在所有 T0.5 之前 —— 这是「前面都是主力」的硬要求
    first_non_t0 = next(i for i, x in enumerate(rows) if x.tier != "0")
    assert all(x.tier == "0" for x in rows[:first_non_t0]), \
        [x.tier for x in rows[:first_non_t0 + 1]]

    # 前面不能出现 T2/T3/cg —— 它们便宜的动作很多，一把梭按 ROI 排就会插上来
    head = [x.tier for x in rows[:first_non_t0 + 1]]
    assert not any(t in ("2", "3", "cg") for t in head), head

    # 已毕业的不在榜上
    from models.targets import panel_progress
    assert not any(x.graduated for x in rows)
    graduated_in_roster = [
        c.name for c in r.characters
        if c.targets and not e.unmet_primary.get(c.name)
        and all(p["done"] for p in panel_progress(c, c.targets))
    ]
    assert graduated_in_roster, "本跑没有已毕业角色，这条断言失去意义"
    assert not (set(graduated_in_roster) & set(names)), "已毕业角色仍出现在榜上"

    # 拉毗：小红帽 —— 折算前她在明细里排 #303，角色榜里必须进 T0 组
    lapi = next(x for x in rows if x.name == "拉毗：小红帽")
    assert lapi.tier == "0" and lapi.rank <= 5, (lapi.tier, lapi.rank)

    # 被跳过（缺物理参数）的角色要说明原因，不能显示成「无事可做」
    queen = next((x for x in rows if x.name == "QUEEN（真）"), None)
    if queen is not None:
        assert queen.best is None and "物理" in queen.no_action_reason, queen.no_action_reason
        assert "物理参数不全" in generate_character_ladder_report(rows)

    # ── CLI 与 GUI 必须同文案 ──
    # 两边都从 character_rows_to_records 取，这里断言它们确实一致 ——
    # 否则会出现「CLI 显示 ⏸ 但 GUI 不显示」这种没人会马上发现的偏差。
    recs = character_rows_to_records(rows)
    assert len(recs) == len(rows), (len(recs), len(rows))
    md = generate_character_ladder_report(rows)
    for rec in recs:
        assert rec["下一步"] in md, f"{rec['角色']} 的下一步文案在 Markdown 里找不到: {rec['下一步']}"
    # ⏸ 标记要跟着走
    gated_rows = [x for x in rows if x.best and x.best.gated]
    assert gated_rows, "本跑没有门禁条目，这条断言失去意义"
    for rec in recs:
        assert rec["gated"] == rec["下一步"].startswith("⏸"), rec

    # ── 展开详情（角色榜点开某一行）──
    det = build_character_detail("拉毗：小红帽", r.characters, bids, e.unmet_primary)
    # 核心词条：优越 4/4 已达标、攻击 3/4 与装弹 2/4 未达标
    prim = {x["buff"]: (x["have"], x["need"], x["done"]) for x in det["primary"]}
    assert prim["优越代码伤害增加"] == (4, 4, True), prim
    assert prim["攻击力增加"] == (3, 4, False), prim
    assert prim["最大装弹数增加"] == (2, 4, False), prim
    # 面板三项，装弹缺口最大
    panel = {x["buff"]: x for x in det["panel"]}
    assert panel["优越代码伤害增加"]["done"] is True
    assert panel["最大装弹数增加"]["gap"] > 140, panel["最大装弹数增加"]
    # 该角色自己的候选动作必须按顺位降序（展开表直接照这个顺序渲染）
    ss = [b.sort_score for b in det["actions"]]
    assert ss == sorted(ss, reverse=True), ss[:5]
    assert det["n_actions"] == len(det["actions"]) == 19, det["n_actions"]

    # 皇冠：核心词条已达成（3 件 ≥ 下限 2），unmet 为空
    crown = build_character_detail("皇冠", r.characters, bids, e.unmet_primary)
    assert crown["unmet"] == [], crown["unmet"]
    assert crown["primary"][0]["buff"] == "最大装弹数增加"
    assert crown["primary"][0]["have"] == 3 and crown["primary"][0]["need"] == 2

    # 娜嘉：推荐表判「无需词条」→ primary 空但不是错误；面板方向用记号表达
    najia = build_character_detail("娜嘉", r.characters, bids, e.unmet_primary)
    assert najia["primary"] == [] and najia["panel"] == []
    assert najia["panel_directives"], "定性面板方向不能悄悄丢掉"
    assert "ANY" in najia["panel_directives"], najia["panel_directives"]
    # 渲染出来的是本仓库自己的文案，不是上游原话
    from models.targets import panel_directive_text
    assert panel_directive_text(najia["panel_directives"])

    # 查无此人 → 空 dict（渲染层据此提示，而不是崩）
    assert build_character_detail("不存在的人", r.characters, bids, {}) == {}

    print(f"角色榜: {len(rows)} 行 | 前 {first_non_t0} 行是 T0 | "
          f"拉毗：小红帽 #{lapi.rank} | CLI/GUI 文案一致 | 展开详情 OK")


def test_panel_progress():
    """毕业进度是纯展示，但数字要对得上装备。"""
    from models.targets import panel_progress
    from engine.roster_loader import load_roster_with_targets

    r = load_roster_with_targets()
    by_name = {c.name: c for c in r.characters}

    # 皇冠：面板只要装弹 120%，她实际 141% → 已达标
    crown = by_name["皇冠"]
    rows = panel_progress(crown, crown.targets)
    assert len(rows) == 1 and rows[0]["buff"] == "最大装弹数增加", rows
    assert rows[0]["done"] is True and rows[0]["gap"] == 0.0, rows

    # 爱丽丝：优越代码一条都没有 → 缺口 80%
    alice = by_name["爱丽丝"]
    rows = {r_["buff"]: r_ for r_ in panel_progress(alice, alice.targets)}
    assert rows["优越代码伤害增加"]["have"] == 0.0, rows["优越代码伤害增加"]
    assert rows["优越代码伤害增加"]["gap"] == 80.0, rows["优越代码伤害增加"]
    assert rows["蓄力速度增加"]["want"] == 8.5, rows["蓄力速度增加"]

    # 阿妮斯：反装弹角色，面板里不该出现装弹
    anis = by_name["阿妮斯：闪耀夏日"]
    assert "最大装弹数增加" not in anis.targets.panel, anis.targets.panel

    print(f"毕业进度: 皇冠已达标 / 爱丽丝 优越 {rows['优越代码伤害增加']['have']:.0f}"
          f"→{rows['优越代码伤害增加']['want']:.0f}%")


def test_history_manager():
    """
    历史记录的增 / 查 / 删。**全程在临时目录里，不碰真实历史。**

    重点测 delete_history 的**安全边界**：它接的是 GUI 传来的字符串路径，
    一旦判断写松（比如只检查 .json 后缀），一个拼错的路径就能删掉别的文件。
    """
    import os
    import shutil
    import tempfile
    from engine.bidding_engine import BidEntry
    import history_manager as hm

    tmp = tempfile.mkdtemp()
    outside = tempfile.mkdtemp()
    old_dir = hm.HISTORY_DIR
    hm.HISTORY_DIR = tmp
    try:
        assert hm.list_history() == [], "新目录应为空"

        bids = [BidEntry(priority=1, character_name="爱丽丝", gear_slot="头",
                         action_type="升级", equivalent_cost=0.1, roi=0.2571,
                         tier="1.5", tier_weight=0.512, sort_score=0.1316),
                BidEntry(priority=2, character_name="皇冠", gear_slot="甲",
                         action_type="洗词条", target_set={"最大装弹数增加"},
                         equivalent_cost=5.0, roi=0.0353, gated=True)]
        path = hm.save_history(bids, 300, 5_000_000, 52)
        assert os.path.exists(path), "save_history 没有真的写出文件"

        # 读回：新字段（门禁/档位）必须还在，否则读回的历史会丢 ⏸ 和档位列
        items = hm.list_history()
        assert len(items) == 1, items
        assert items[0]["total_bids"] == 2
        assert items[0]["size"] > 0, "list_history 应带上文件体积"
        back = hm.load_history(path)
        assert back["bids"][1]["gated"] is True, back["bids"][1]
        assert back["bids"][0]["tier"] == "1.5", back["bids"][0]

        # 删除：真的删掉
        assert hm.delete_history(path) is True
        assert not os.path.exists(path)
        assert hm.list_history() == []

        # 再删同一路径 → False（不报错，只是没删成）
        assert hm.delete_history(path) is False

        # ── 安全边界 ──
        # 目录外的 .json：拒绝
        outsider = os.path.join(outside, "别的重要文件.json")
        with open(outsider, "w", encoding="utf-8") as f:
            f.write("{}")
        assert hm.delete_history(outsider) is False, "删了 data/history/ 之外的文件！"
        assert os.path.exists(outsider), "目录外的文件被删掉了"

        # 目录内但不是 .json：拒绝
        stray = os.path.join(tmp, "notes.txt")
        with open(stray, "w", encoding="utf-8") as f:
            f.write("x")
        assert hm.delete_history(stray) is False

        print("历史记录: 存/读/删 OK | 新字段(门禁/档位)随记录保存 | "
              "目录外路径已拒绝")
    finally:
        hm.HISTORY_DIR = old_dir
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(outside, ignore_errors=True)


def test_alias_coverage():
    """
    别名表必须能解释上游语料里的全部词条写法。

    这是防回归的关键一项：上游改了写法、或别名表被误删，这里会失败，
    而不是等到某条目标词条被静默丢弃、ROI 悄悄算偏。

    依赖快照生成侧的 verify_alias_coverage.py 与原始语料（均不在仓库内），
    见 _NEEDS_SNAPSHOT_TOOLING。本机保留脚本即可继续跑。
    """
    import subprocess
    repo = Path(__file__).resolve().parent.parent
    r = subprocess.run(
        [sys.executable, "verify_alias_coverage.py"],
        cwd=repo, capture_output=True, text=True,
    )
    if r.returncode != 0:
        print(r.stdout)
        raise AssertionError("别名表覆盖不足，见上方残渣清单")
    tail = [ln for ln in r.stdout.splitlines() if "无残渣" in ln or "共扫描" in ln]
    print(" | ".join(tail))


if __name__ == "__main__":
    print(f"常数: 硬直动画={HARD_ANIM_SEC}s, 秒蓄判定线={INSTANT_CHARGE_LINE}\n")
    tests = [
        test_physical_config,
        test_cs_multiplier,
        test_ammo_multiplier,
        test_expected_cost,
        test_damage_model,
        test_build_char_summary,
        test_roster_loader,
        test_roster_dirty_data_handling,
        test_targets_snapshot,
        test_tier_weighting,
        test_character_ladder,
        test_panel_progress,
        test_history_manager,
        test_alias_coverage,
    ]
    has_own_roster = _OWN_ROSTER.exists()
    has_tooling = all(p.exists() for p in _SNAPSHOT_TOOLING_MARKERS)

    if not has_own_roster:
        print(f"⏭️  未找到 {_OWN_ROSTER.relative_to(_OWN_ROSTER.parent.parent)} —— "
              f"真实名册属个人数据，不入库，下列测试将跳过：")
        print(f"   {', '.join(sorted(_NEEDS_OWN_ROSTER))}")
        print(f"   （放一份自己的 input/cn_collect.json 即可恢复；"
              f"格式样例见 input/cn_collect.sample.json）\n")

    if not has_tooling:
        absent = [p.name for p in _SNAPSHOT_TOOLING_MARKERS if not p.exists()]
        print(f"⏭️  未找到快照生成工具 {', '.join(absent)} —— "
              f"该工具不在仓库内（仓库只分发定稿快照），下列测试将跳过：")
        print(f"   {', '.join(sorted(_NEEDS_SNAPSHOT_TOOLING))}")
        print(f"   （本机保留一份即可恢复）\n")

    skipped: list[str] = []
    reasons: set[str] = set()
    for t in tests:
        if t.__name__ in _NEEDS_OWN_ROSTER and not has_own_roster:
            skipped.append(t.__name__)
            reasons.add("缺个人名册")
            continue
        if t.__name__ in _NEEDS_SNAPSHOT_TOOLING and not has_tooling:
            skipped.append(t.__name__)
            reasons.add("缺快照生成工具")
            continue
        t()
        print()

    passed = len(tests) - len(skipped)
    if skipped:
        print(f"✅ {passed} 项通过 / ⏭️  {len(skipped)} 项跳过（{'、'.join(sorted(reasons))}）")
    else:
        print(f"✅ {len(tests)} 项全部通过")
