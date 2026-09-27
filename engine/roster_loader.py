"""
上游「实际表」加载：input/cn_collect.json → models.Character

上游格式的权威说明见 input/数据说明.md。这里只强调引擎侧必须记住的三条：

1. **数值是小数量纲**（`0.1181` = 11.81%）。`BuffLine.value_pct` 用百分比，
   所以读入时 ×100；`config.value_to_tier` 也吃百分比。
2. **词条位不是顺序填充的**。`XEX`（第 1、3 条有词条、第 2 条空）有 21 个槽，
   所以一律按「3 个独立槽位」处理，不假设空位会排在后面。
3. **三种空态语义不同**（混为一谈会把 T9 当成「T10 但没词条」）：
     - 整槽三条 `名称` 全为 null  → **T9**，没有改造装备效果，属预期
     - `名称` == `未获得效果`      → **T10**，但该词条位是空的
     - `名称` 有值、`数值` 为 null → **脏数据**，报警不兜底

绝不静默：词条名不在 `config.TIER_VALUE_MATRIX` 里直接抛错（命名铁律），
数值不在 15 档上由 `value_to_tier` 抛错，脏数据记进 `issues` 由调用方打印。
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from config import EMPTY_BUFF_NAME, GEAR_SLOTS, MAX_LEVEL, TIER_VALUE_MATRIX, value_to_tier
from models.buff import BuffLine
from models.character import Character
from models.gear import Gear
from models.targets import PARSED_PATH as PARSED_TARGETS_PATH, CharTargets

# 上游文件名只是采集脚本的默认名，提交时可改名（见 input/数据说明.md 第一节）。
# 要换数据源就传绝对路径给 load_roster()。
ROSTER_PATH = "input/cn_collect.json"

# 上游字段名。集中在这里，格式漂移时改一处，报错信息也能指到具体位置。
KEY_ROSTER = "角色"       # 顶层唯一的键；不是它说明文件不是上游产物
KEY_NAME = "姓名"
KEY_LEVEL = "等级"
KEY_LINES = "词条"
KEY_BUFF = "名称"
KEY_VALUE = "数值"

# issue 的 kind 取值
KIND_MISSING_VALUE = "缺数值"
KIND_MISSING_LEVEL = "缺等级"
KIND_NAME_NULL = "词条名为空"


@dataclass
class RosterIssue:
    """一条需要人工看一眼的数据异常。留空 + 报警，不做兜底。"""
    character: str
    slot: str
    line_index: int          # 0-2；-1 表示整槽
    kind: str
    detail: str

    def __str__(self) -> str:
        where = f"{self.character}·{self.slot}"
        if self.line_index >= 0:
            where += f"·第{self.line_index + 1}条"
        return f"[{self.kind}] {where} — {self.detail}"


@dataclass
class RosterParseResult:
    """加载结果。`characters` 直接喂给 GlobalBiddingEngine。"""
    characters: List[Character] = field(default_factory=list)
    issues: List[RosterIssue] = field(default_factory=list)
    # 名字为空、无法建 Character 的条目
    skipped: List[str] = field(default_factory=list)
    # 推荐表里查无此人的角色（图鉴未收录），拿不到养成目标
    unmatched_targets: List[str] = field(default_factory=list)

    # ── 统计（用于打印加载报告，也是数据健康度的冒烟指标）──
    t9_slots: int = 0            # 整槽没有 T10
    t10_slots: int = 0
    buff_lines: int = 0          # 真实词条条数（不含 未获得效果）
    empty_placeholders: int = 0  # 「未获得效果」占位符条数
    t9_level_unknown: int = 0    # T9 槽上游 等级 为 null 的个数
    # ── 目标接入情况 ──
    mode: str = ""               # 本跑用的模式（PVE/PVP）
    targets_attached: bool = False

    def format_report(self) -> str:
        lines = [
            f"  名册: {len(self.characters)} 角色 / "
            f"{self.t10_slots + self.t9_slots} 槽 "
            f"(T10 {self.t10_slots} + T9 {self.t9_slots})",
            f"  词条: {self.buff_lines} 条真实词条 + {self.empty_placeholders} 个空占位",
        ]
        if self.skipped:
            lines.append(f"  ⚠️ 跳过无名条目 {len(self.skipped)} 个: {', '.join(self.skipped)}")
        if self.t9_level_unknown:
            lines.append(
                f"  ⚠️ {self.t9_level_unknown} 个 T9 槽「等级」为 null（采集时上游没给），"
                f"本跑按 Lv0 处理 —— 可能给出偏乐观的 升级 竞价"
            )
        if self.targets_attached:
            n_with = sum(1 for c in self.characters if c.targets and c.targets.primary)
            n_none = sum(1 for c in self.characters if c.targets and not c.targets.primary)
            lines.append(
                f"  目标({self.mode}): {n_with} 人有主目标 / {n_none} 人判为「无需」"
            )
            if self.unmatched_targets:
                lines.append(
                    f"  ⚠️ 推荐表查无此人 {len(self.unmatched_targets)} 个（拿不到目标）: "
                    f"{', '.join(self.unmatched_targets)}"
                )
        else:
            lines.append(
                "  ⛔ 目标词条未接入：洗词条/洗数值/开光 全部为 0 条，本跑只剩「升级」类竞价。"
                "这不是「已毕业」。请确认 data/targets_parsed.json（随仓库分发的快照）"
                "存在，且能被 load_targets() 读出。"
            )
        if self.issues:
            lines.append(f"  ⚠️ 数据异常 {len(self.issues)} 处（留空 + 报警，未兜底）:")
            lines.extend(f"     {i}" for i in self.issues)
        return "\n".join(lines)


# ────────────────────────────────────────────────────────────
# 单槽解析
# ────────────────────────────────────────────────────────────

def _parse_slot(
    character: str, slot: str, raw_slot: dict
) -> tuple[Gear, List[RosterIssue], dict]:
    """
    解析一个装备槽。

    返回 (Gear, issues, 计数)。计数含 t9/t10/buff_lines/empty_placeholders/
    level_unknown 五项，由调用方累加。
    """
    issues: List[RosterIssue] = []
    counts = {
        "t9": 0, "t10": 0, "buff_lines": 0,
        "empty_placeholders": 0, "level_unknown": 0,
    }

    entries = raw_slot.get(KEY_LINES) or []

    # 上游恒定给 3 条（不足的用占位符补齐）。条数不对说明格式漂移，
    # 报错而不是补齐 —— 补齐会掩盖「少读了一条」这种错误。
    if len(entries) != 3:
        raise ValueError(
            f"{character}·{slot} 的词条条数为 {len(entries)}，上游约定恒为 3 条。"
            f"请核对 input/数据说明.md 与 input/cn_collect.json。"
        )

    # ── T9：三条名称全为 null ──
    if all(e.get(KEY_BUFF) is None for e in entries):
        counts["t9"] = 1
        level = raw_slot.get(KEY_LEVEL)
        if level is None:
            # 上游对 T9 槽不给等级（96/96）。按 Lv0 起算是既定决定，
            # 但要计数报警 —— 它会让「升级」竞价显得比实际更划算。
            counts["level_unknown"] = 1
            level = 0
        return (
            Gear(slot=slot, level=level, lines=[BuffLine() for _ in range(3)]),
            issues,
            counts,
        )

    # ── T10 ──
    counts["t10"] = 1
    level = raw_slot.get(KEY_LEVEL)
    if level is None:
        issues.append(RosterIssue(
            character, slot, -1, KIND_MISSING_LEVEL,
            "该槽有改造词条（属 T10），但上游没给强化等级；按 Lv0 处理",
        ))
        level = 0
    elif not 0 <= level <= MAX_LEVEL:
        raise ValueError(f"{character}·{slot} 的强化等级 {level} 越界（应为 0-{MAX_LEVEL}）")

    lines: List[BuffLine] = []
    for i, entry in enumerate(entries):
        name = entry.get(KEY_BUFF)
        value = entry.get(KEY_VALUE)

        # 整槽已判过 T9，这里再出现 null 名称说明同槽混了两种形态，是格式漂移
        if name is None:
            issues.append(RosterIssue(
                character, slot, i, KIND_NAME_NULL,
                "该槽已判定为 T10（存在具名词条），此条名称却为 null；按空槽处理",
            ))
            lines.append(BuffLine())
            continue

        # 空词条位（游戏内原文占位符）。它不是「没有 T10」，见 config.EMPTY_BUFF_NAME。
        if name == EMPTY_BUFF_NAME:
            counts["empty_placeholders"] += 1
            if value not in (0, None):
                issues.append(RosterIssue(
                    character, slot, i, KIND_MISSING_VALUE,
                    f"「{EMPTY_BUFF_NAME}」的数值应为 0，实际为 {value}；按空槽处理",
                ))
            lines.append(BuffLine())
            continue

        # 命名铁律：非标准名一律抛错，不做别名翻译（那是 buff_aliases.py 的活）。
        if name not in TIER_VALUE_MATRIX:
            raise KeyError(
                f"{character}·{slot}·第{i + 1}条 词条名 '{name}' 不是标准名。"
                f"标准名见 config.BUFF_NAMES；上游应给游戏内原文。"
            )

        # 有名称无数值 = 脏数据。按项目既定政策「留空 + 报警」处理：
        # 不猜档位、也不假装这条词条不存在于计算里 —— 两者都是把「不知道」伪装成「知道」。
        # 目前全库仅 1 处（白雪公主 头第 2 条）。
        if value is None:
            issues.append(RosterIssue(
                character, slot, i, KIND_MISSING_VALUE,
                f"「{name}」的数值为 null，无法反查档位；该条按空槽留空。"
                f"需在采集侧补上该数值。",
            ))
            lines.append(BuffLine())
            continue

        # 小数 → 百分比。上游 0.1181 = 11.81%。
        value_pct = value * 100.0
        tier = value_to_tier(name, value_pct)   # 越档抛错，不取最近档
        counts["buff_lines"] += 1
        lines.append(BuffLine(buff_type=name, tier=tier, value_pct=value_pct))

    return Gear(slot=slot, level=level, lines=lines), issues, counts


# ────────────────────────────────────────────────────────────
# 名册解析
# ────────────────────────────────────────────────────────────

def parse_roster(
    data: dict,
    targets_by_name: Optional[Dict[str, CharTargets]] = None,
) -> RosterParseResult:
    """
    从已解析的 JSON dict 建名册。

    Args:
        data: 顶层形如 {"角色": [...]}。GUI 上传的文件也走这里。
        targets_by_name: 可选，角色名 → models.targets.CharTargets。
            由 models.targets.load_targets() 从 data/targets_parsed.json 读出。
            缺省则角色没有目标词条并报警 —— 绝不编造默认目标。
    """
    if not isinstance(data, dict) or KEY_ROSTER not in data:
        raise ValueError(
            f"上游名册顶层应有 {KEY_ROSTER!r} 键，实际是 "
            f"{type(data).__name__}{list(data)[:5] if isinstance(data, dict) else ''}。"
            f"见 input/数据说明.md 第一节。"
        )

    result = RosterParseResult(targets_attached=bool(targets_by_name))

    for raw in data[KEY_ROSTER]:
        name = (raw.get(KEY_NAME) or "").strip()
        if not name:
            result.skipped.append(repr(raw)[:80])
            continue

        char = Character(name=name)
        # targets 是引擎拿养成目标的唯一入口（见 models/targets.py）。
        # 没有推荐表就留 None，绝不编造默认目标。
        if targets_by_name and name in targets_by_name:
            char.targets = targets_by_name[name]
        else:
            result.unmatched_targets.append(name)

        for slot in GEAR_SLOTS:
            raw_slot = raw.get(slot)
            if not isinstance(raw_slot, dict):
                raise ValueError(f"{name} 缺少 {slot} 槽，或该槽不是对象。")

            gear, issues, counts = _parse_slot(name, slot, raw_slot)
            char.gears[slot] = gear
            result.issues.extend(issues)
            result.t9_slots += counts["t9"]
            result.t10_slots += counts["t10"]
            result.buff_lines += counts["buff_lines"]
            result.empty_placeholders += counts["empty_placeholders"]
            result.t9_level_unknown += counts["level_unknown"]

        char.ensure_gears()
        result.characters.append(char)

    return result


def load_roster(
    roster_path: str = ROSTER_PATH,
    targets_by_name: Optional[Dict[str, CharTargets]] = None,
    mode: str = "",
) -> RosterParseResult:
    """
    读上游名册文件。路径写错就报错，不静默返回空名册。

    Args:
        targets_by_name: load_targets() 的产物。缺省 = 没接推荐表（会报警）。
        mode: 本跑用的模式，仅用于报告展示。
    """
    path = Path(roster_path)
    if not path.exists():
        raise FileNotFoundError(
            f"上游名册不存在: {roster_path}。"
            f"预期是 input/cn_collect.json（格式见 input/数据说明.md）。"
        )

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    result = parse_roster(data, targets_by_name)
    result.mode = mode
    return result


def load_roster_with_targets(
    roster_path: str = ROSTER_PATH,
    targets_path: str = PARSED_TARGETS_PATH,
    mode: str = "PVE",
) -> RosterParseResult:
    """
    名册 + 目标一次装好 —— 入口该用的就是这个。

    目标文件缺失时**不静默降级**：那会让一份只剩「升级」类竞价的残缺天梯
    看起来像完整结果。直接抛错，让人先恢复那份快照。
    """
    from models.targets import load_targets

    targets_by_name = load_targets(targets_path, mode=mode)
    return load_roster(roster_path, targets_by_name, mode=mode)
