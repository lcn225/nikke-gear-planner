"""
角色模型：角色名 + 装备状态 + 养成目标

`rule_type` / `rule_params` 已删除（2026-09-25）：那套 `TYPE_EXACT_MATRIX` 之类的
决策规则早被全局竞价取代（`TYPE_DYNAMIC_STRATEGY` 当初就是为此而设），字段沦为
没人读的死数据。目标词条现在走 `targets`，带主副分层与件数。
"""

from dataclasses import dataclass, field
from typing import Optional

from .gear import Gear
from .targets import CharTargets
from config import GEAR_SLOTS


@dataclass
class Character:
    """一个妮姬角色及其装备和养成目标"""
    name: str
    # 养成目标。由 engine/roster_loader.py 从 data/targets_parsed.json 注入。
    # 没接上推荐表时为 None —— 引擎会报警，绝不静默当成「已毕业」。
    targets: Optional[CharTargets] = None
    # 死字段，等跨角色折算。引擎算 ΔB 用的是「该角色**自身**伤害」的增幅，
    # 辅助型的收益因此被系统性高估：皇冠一条装弹 ΔB=17.7%，爱丽丝只有 11.4%，
    # 但皇冠自身伤害可能只占全队 1%。真要修需要「该角色伤害占全队比重」这个
    # 目前**没有任何来源**的输入，所以先留着，不要在别处补主观系数。
    strategy_weight: float = 1.0
    gears: dict[str, Gear] = field(default_factory=dict)

    # ── 便捷查询 ──

    def get_all_gears(self) -> list[Gear]:
        """按标准顺序返回 4 件装备"""
        return [self.gears[slot] for slot in GEAR_SLOTS if slot in self.gears]

    def count_buff_across_all(self, buff_name: str) -> int:
        """
        统计全套 4 件装备中，指定词条的总出现次数（按装备件数）。

        上游数据里同一件装备不会重复出现同一词条（已核对 0 处），
        所以「件数」与「条数」等价，这个口径就是 primary 达成判定要用的。
        """
        return sum(1 for gear in self.get_all_gears() if gear.count_buff(buff_name) > 0)

    def ensure_gears(self):
        """确保 4 个部位都有装备对象（默认空装备）"""
        for slot in GEAR_SLOTS:
            if slot not in self.gears:
                self.gears[slot] = Gear(slot=slot)

    # ── 序列化 ──

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "strategy_weight": self.strategy_weight,
            "gears": {slot: gear.to_dict() for slot, gear in self.gears.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Character":
        """从字典创建角色。targets 不在序列化里，由 roster_loader 单独注入。"""
        char = cls(
            name=data["name"],
            strategy_weight=data.get("strategy_weight", 1.0),
            gears={slot: Gear.from_dict(g) for slot, g in data.get("gears", {}).items()},
        )
        char.ensure_gears()
        return char

    def __str__(self) -> str:
        n = len(self.targets.primary) if self.targets else 0
        return f"[{self.name}] weight={self.strategy_weight} primary={n}"
