# -*- coding: utf-8 -*-
"""
养成目标数据模型 + 读取 `data/targets_parsed.json`（随仓库分发的静态快照）。

这里只重复引擎侧必须记住的三条：

1. **primary / secondary 是「先做哪个」**。primary 未达成时，该角色只出 primary 相关
   的竞价；secondary 候选仍会被算出来，但标注为「待 primary 达成」列在天梯里 ——
   强制顺序，但不丢信息。
2. **panel 是毕业状态（终点）**，独立于主副，只用于展示「距毕业还差多少」。
   它**不参与**任何判定 —— 蓄速门槛那类「够了就别再洗」由伤害模型自己的封顶处理。
3. **件数是中等档位口径的估计，不是硬需求**。达成判定用它，但不要求恰好等于：
   `*N` 与 `（至少N条）` 取下限 N，裸名/任意/越多越好 取 1。

本模块读 `data/targets_parsed.json`。它是清洗后的快照：上游推荐表的散文已归一成
结构化的词条目标，并剔除了评测正文。

字段语义见 `data/targets_parsed.json` 的 `_meta.note`。
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from config import TIER_VALUE_MATRIX

PARSED_PATH = "data/targets_parsed.json"

_DEFAULT_MODE = "PVE"

# ────────────────────────────────────────────────────────────
# 面板方向记号
#
# 上游推荐表在「毕业方向是定性的」时只给一句话（如「随意刷取」）。快照里
# **不收那句话的原文**，只收它的**含义**编码成下面这几个记号；给用户看的文案
# 由本仓库自己生成。这样既留下信息，又不再分发上游正文。
#
# 加记号要慎重：每个都得对应真实存在的一类含义，别为了塞进某条语料现编。
# ────────────────────────────────────────────────────────────

PANEL_DIRECTIVES: dict[str, str] = {
    "ANY":          "无硬性数值目标，达成主副词条即可",
    "LOW_PRIORITY": "培养优先级不高，不建议投入过多资源",
    "OUTDATED":     "角色已被淘汰，不推荐为其投入",
    "SUPPORT_SKIP": "辅助角色，可不投资或少投资",
    "EXCLUDE_AMMO": "注意：装弹词条对该角色为负收益",
    "EXCLUDE_CS":   "注意：不需要蓄力速度词条",
    "FOLLOW_PVP":   "建议跟随 PVP 方案",
}


def _directives(raw) -> List[str]:
    """校验记号表。未知记号直接抛错，不静默忽略 —— 静默会让「新记号没接上」
    表现成「这条建议凭空消失」。"""
    out: List[str] = []
    for code in raw or []:
        if code not in PANEL_DIRECTIVES:
            raise ValueError(f"未知的面板方向记号 {code!r}，不在 PANEL_DIRECTIVES 中")
        if code not in out:
            out.append(code)
    return out


def panel_directive_text(directives: List[str]) -> str:
    """把记号渲染成给用户看的一句话（文案由本仓库给出，非上游原文）。"""
    return "；".join(PANEL_DIRECTIVES[c] for c in directives)


@dataclass
class TargetSpec:
    """一个目标词条（或互斥组的一员）。"""
    buff: str                     # 标准名
    count: Optional[int] = None   # 件数下限；None = 攻略作者没规定
    count_kind: str = "unspecified"
    count_max: Optional[int] = None
    group: Optional[str] = None
    source: str = ""

    @property
    def floor(self) -> int:
        """
        达成判定用的件数下限。

        `*4` 与 `（至少2条）` 取下限本身；「任意」「越多越好」「裸名」这类
        没规定的取 1 —— 不是 0（那等于没有目标），也不是猜一个大数。
        """
        return self.count if self.count is not None else 1


@dataclass
class CharTargets:
    """一个角色在某个模式下的全部目标。"""
    mode: str
    primary: List[TargetSpec] = field(default_factory=list)
    secondary: List[TargetSpec] = field(default_factory=list)
    panel: Dict[str, float] = field(default_factory=dict)   # 标准名 -> 毕业总量(%)
    groups: List[dict] = field(default_factory=list)
    # 毕业方向为定性时的**结构化记号**（不是上游原话）。见 PANEL_DIRECTIVES。
    panel_directives: List[str] = field(default_factory=list)
    # 培养优先级（角色级，与 mode 无关）。引擎用它做跨角色折算，
    # 见 config.tier_weight。scores 是分模式评分，目前只存不用。
    tier: str = ""
    scores: Dict[str, str] = field(default_factory=dict)

    @property
    def weight(self) -> float:
        from config import tier_weight
        return tier_weight(self.tier)

    def primary_buffs(self) -> List[str]:
        return sorted({t.buff for t in self.primary})

    def secondary_buffs(self) -> List[str]:
        return sorted({t.buff for t in self.secondary})

    def all_buffs(self) -> List[str]:
        """引擎的 targets 集合语义用这个：primary ∪ secondary。"""
        return sorted({t.buff for t in self.primary} | {t.buff for t in self.secondary})


def _spec(d: dict) -> TargetSpec:
    return TargetSpec(
        buff=d["buff"],
        count=d.get("count"),
        count_kind=d.get("count_kind", "unspecified"),
        count_max=d.get("count_max"),
        group=d.get("group"),
        source=d.get("source", ""),
    )


def _char_targets(mode: str, ch: dict) -> CharTargets:
    d = ch["modes"][mode]
    # 面板项列表 → {标准名: 总量}。同一词条出现多次时取最大（面板是上限目标）。
    panel: Dict[str, float] = {}
    for p in d.get("panel") or []:
        b, v = p["buff"], float(p["total_pct"])
        if b not in panel or v > panel[b]:
            panel[b] = v

    return CharTargets(
        mode=mode,
        primary=[_spec(x) for x in d.get("primary") or []],
        secondary=[_spec(x) for x in d.get("secondary") or []],
        panel=panel,
        groups=list(d.get("groups") or []),
        panel_directives=_directives(d.get("panel_directives")),
        tier=str(ch.get("tier") or ""),
        scores=dict(ch.get("scores") or {}),
    )


def load_targets(
    parsed_path: str = PARSED_PATH,
    mode: str = _DEFAULT_MODE,
) -> Dict[str, CharTargets]:
    """
    读归一后的推荐表。返回 {角色名: CharTargets}。

    角色在该模式下没有 primary/secondary/panel 三者中任何一项时**仍然返回**，
    只是各项为空 —— 「无需词条」是合法数据（超级辅助王的词条只影响战力），
    不是缺失。调用方据此区分「有目标但为空」与「根本没有这个角色」。
    """
    path = Path(parsed_path)
    if not path.exists():
        raise FileNotFoundError(
            f"推荐表快照不存在: {parsed_path}。该文件随仓库分发，"
            f"若缺失请从仓库重新获取。"
        )

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "characters" not in data:
        raise ValueError(
            f"{parsed_path} 顶层应有 characters 键。"
            f"该文件是随仓库分发的快照，不要手改。"
        )

    out: Dict[str, CharTargets] = {}
    missing_mode: List[str] = []
    for name, ch in data["characters"].items():
        if mode not in (ch.get("modes") or {}):
            missing_mode.append(name)
            continue
        out[name] = _char_targets(mode, ch)

    if missing_mode:
        # 不静默：某个模式整批缺失说明快照生成时出了问题，不是「这些角色没目标」
        raise ValueError(
            f"{parsed_path} 里 {len(missing_mode)} 个角色没有 {mode!r} 模式"
            f"（例: {missing_mode[:5]}）。可用模式见该文件。"
        )

    return out


# ────────────────────────────────────────────────────────────
# 历史记录自带的目标切片
#
# 历史记录要能独立回放角色榜，就得连同「当时用的是哪份目标」一起存 ——
# 角色榜是 f(名册, 竞价, 门禁) 的函数，少了目标就重建不出来；而改用**当前**
# 的目标表重建，得到的是「旧名册 × 新目标」，正是 R1a 修掉的那类混源。
#
# 存的是**原始切片**而不是解析好的 CharTargets：读回时走同一个 `_char_targets`，
# 与当时跑计算走的是同一条解析路径。存解析结果等于把解析逻辑抄一份进历史文件，
# 两边一旦走偏，从文件本身看不出来。
# ────────────────────────────────────────────────────────────

def snapshot_targets(
    names: List[str],
    mode: str,
    parsed_path: str = PARSED_PATH,
) -> Dict[str, dict]:
    """
    切出这批角色在 mode 下的目标，供历史记录自带。

    只保留 `_char_targets` 真正读的键（`tier` / `scores` / `modes[mode]`），
    另一个模式不带 —— 历史只回放它当时用的那一次。实测这套切片约 79KB，
    相对一份约 900KB 的竞价明细是可以接受的代价。

    名册里查无此人的角色**直接不进来**（与当次运行一致：那次也没有目标，
    加载报告里的「推荐表查无此人」才是报警的地方）。但角色在、模式不在
    是另一回事 —— 那说明快照文件本身残缺，`load_targets` 当时就会抛错，
    这里同样抛错，不静默少一条。
    """
    path = Path(parsed_path)
    if not path.exists():
        raise FileNotFoundError(
            f"推荐表快照不存在: {parsed_path}。该文件随仓库分发，"
            f"若缺失请从仓库重新获取。"
        )

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "characters" not in data:
        raise ValueError(
            f"{parsed_path} 顶层应有 characters 键。"
            f"该文件是随仓库分发的快照，不要手改。"
        )

    chars = data["characters"]
    out: Dict[str, dict] = {}
    for name in names:
        ch = chars.get(name)
        if ch is None:
            continue
        if mode not in (ch.get("modes") or {}):
            raise ValueError(
                f"{parsed_path} 里 {name} 没有 {mode!r} 模式。"
                f"可用模式见该文件。"
            )
        out[name] = {
            "tier": ch.get("tier"),
            "scores": ch.get("scores"),
            "modes": {mode: ch["modes"][mode]},
        }
    return out


def load_targets_from_snapshot(snapshot: dict, mode: str) -> Dict[str, CharTargets]:
    """
    从历史记录自带的目标切片重建 `{角色名: CharTargets}`。

    `snapshot` 是 `snapshot_targets` 的产物（原样存在历史文件里）。
    缺 mode 一律抛错：那说明这份切片不是按同一个模式生成的，
    拿它重建等于给角色榜配错目标 —— 宁可读不出来，也不要一张看着正常的错表。
    """
    out: Dict[str, CharTargets] = {}
    for name, ch in snapshot.items():
        if mode not in (ch.get("modes") or {}):
            raise ValueError(
                f"历史记录自带的目标切片里 {name} 没有 {mode!r} 模式；"
                f"这条记录可能是别的模式生成的，或文件被改动过。"
            )
        out[name] = _char_targets(mode, ch)
    return out


# ────────────────────────────────────────────────────────────
# 毕业进度（展示用，不参与判定）
# ────────────────────────────────────────────────────────────

def primary_progress(char, targets: CharTargets) -> List[dict]:
    """
    核心词条（primary）的达成情况，供角色展开视图用。

    判据与门禁一致：全套 4 件装备里该词条的**件数** ≥ 它自己声明的下限
    （`*N` 与 `（至少N条）` 取 N；裸名/任意/越多越好 取 1）。
    """
    rows = []
    seen = set()
    for spec in targets.primary:
        if spec.buff in seen:
            continue
        seen.add(spec.buff)
        have = char.count_buff_across_all(spec.buff)
        rows.append({
            "buff": spec.buff,
            "have": have,
            "need": spec.floor,
            "done": have >= spec.floor,
            "count_kind": spec.count_kind,
            "source": spec.source,
        })
    return rows


def panel_progress(char, targets: CharTargets) -> List[dict]:
    """
    当前装备 vs 毕业面板，逐词条给出总量差。

    **纯展示**。引擎的竞价排序不看它 —— 洗数值的收益由伤害模型给，
    蓄速够不够由 `compute_m_cs` 的门槛封顶给，这里只回答「离毕业多远」。

    Args:
        char: models.Character（需要 .gears）
        targets: 该角色的 CharTargets
    """
    current: Dict[str, float] = {}
    for gear in char.gears.values():
        for line in gear.lines:
            if not line.is_empty:
                current[line.buff_type] = current.get(line.buff_type, 0.0) + line.value_pct

    rows = []
    for buff, want in sorted(targets.panel.items(), key=lambda kv: -kv[1]):
        have = current.get(buff, 0.0)
        rows.append({
            "buff": buff,
            "have": round(have, 2),
            "want": want,
            "gap": round(max(0.0, want - have), 2),
            "done": have >= want,
            "modeled": buff in TIER_VALUE_MATRIX,
        })
    return rows
