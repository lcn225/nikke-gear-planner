"""
词条数据模型：BuffLine（装备上的具体词条）
"""

from dataclasses import dataclass


@dataclass
class BuffLine:
    """装备上的一个词条槽位"""
    # 词条标准名（游戏内原文），如 "攻击力增加"、"优越代码伤害增加"。
    # 空字符串表示空槽 —— 注意与 config.EMPTY_BUFF_NAME("未获得效果") 不同：
    # 后者是上游 T10 空词条位的占位符，读入时归一成空槽（见 engine/roster_loader.py）。
    buff_type: str = ""
    tier: int = 0                # 档位 1-15，0 表示无词条
    value_pct: float = 0.0       # 实际数值百分比，如 11.81 表示 11.81%

    @property
    def is_empty(self) -> bool:
        return self.buff_type == "" or self.tier == 0

    def __str__(self) -> str:
        if self.is_empty:
            return "[空]"
        return f"{self.buff_type}/{self.tier}档"
