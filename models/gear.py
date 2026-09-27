"""
装备模型：一个妮姬有 4 个装备部位，每个部位有等级（0-5）和 3 个词条槽
"""

from dataclasses import dataclass, field
from .buff import BuffLine


@dataclass
class Gear:
    """单件装备（头/甲/手/脚之一）"""
    slot: str                    # 部位名："头" / "甲" / "手" / "脚"（游戏内 2×2 的左上/右上/左下/右下）
    level: int = 0               # 强化等级 0-5
    lines: list = field(default_factory=lambda: [
        BuffLine(), BuffLine(), BuffLine()
    ])

    # ── 词条查询方法 ──

    def count_buff(self, buff_name: str) -> int:
        """统计该装备上指定词条的出现次数"""
        return sum(1 for line in self.lines if line.buff_type == buff_name)

    def has_buffs(self, names: list[str]) -> bool:
        """检查是否同时拥有列表中所有的词条（每种至少1条）"""
        return all(self.count_buff(n) >= 1 for n in names)

    def missing_from(self, required: list[str]) -> list[str]:
        """返回 required 中该装备缺少的词条名称列表"""
        return [n for n in required if self.count_buff(n) == 0]

    def valid_buff_count(self, valid_set: set[str]) -> int:
        """统计有效词条数量（词条类型在 valid_set 中的总条数）"""
        return sum(1 for line in self.lines if line.buff_type in valid_set)

    def empty_slot_count(self) -> int:
        """统计空槽位数"""
        return sum(1 for line in self.lines if line.is_empty)

    def locked_count(self) -> int:
        """统计已锁定（非空）词条数，用于计算洗练消耗"""
        return sum(1 for line in self.lines if not line.is_empty)

    def non_empty_lines(self) -> list[BuffLine]:
        """返回所有非空词条"""
        return [line for line in self.lines if not line.is_empty]

    # ── 等级相关 ──

    @property
    def is_max_level(self) -> bool:
        return self.level >= 5

    def upgrade_cost(self, costs: list[int]) -> int:
        """获取从当前等级升级到下一级所需的信用点"""
        if self.is_max_level:
            return 0
        return costs[self.level] if self.level < len(costs) else 0

    def upgrade_cp_gain(self, cp_gains: list[int]) -> int:
        """获取从当前等级升级到下一级的战力提升"""
        if self.is_max_level:
            return 0
        return cp_gains[self.level] if self.level < len(cp_gains) else 0

    # ── 序列化 ──

    def to_dict(self) -> dict:
        return {
            "slot": self.slot,
            "level": self.level,
            "lines": [
                {"buff_type": l.buff_type, "tier": l.tier, "value_pct": l.value_pct}
                for l in self.lines
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Gear":
        lines = [
            BuffLine(
                buff_type=l.get("buff_type", ""),
                tier=l.get("tier", 0),
                value_pct=l.get("value_pct", 0.0),
            )
            for l in data.get("lines", [])
        ]
        # 确保始终有 3 个槽位
        while len(lines) < 3:
            lines.append(BuffLine())
        return cls(slot=data["slot"], level=data.get("level", 0), lines=lines[:3])

    def __str__(self) -> str:
        level_str = f"Lv.{self.level}"
        line_strs = [str(l) for l in self.lines]
        return f"[{self.slot}] {level_str} | " + " | ".join(line_strs)
