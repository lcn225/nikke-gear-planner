# engine/__init__.py

from .damage_model import (
    CharPhysicalProfile,
    CharSummary,
    get_profile,
    build_char_summary,
    compute_relative_gain,
    compute_total_damage_factor,
    compute_m_atk,
    compute_m_atk_upgrade,
    compute_m_ele,
    compute_m_ammo,
    compute_m_cs,
    compute_m_crit,
)

from .probability import (
    expected_stones_reroll_type,
    expected_stones_reroll_value,
    expected_stones_first_activation,
    count_targets_on_gear,
    count_low_tier_targets,
    expected_cost_to_achieve_targets,  # 新函数
)

from .bidding_engine import (
    GlobalBiddingEngine,
    BidEntry,
    generate_unified_ladder_report,
)

__all__ = [
    # damage_model
    "CharPhysicalProfile",
    "CharSummary",
    "get_profile",
    "build_char_summary",
    "compute_relative_gain",
    "compute_total_damage_factor",
    "compute_m_atk",
    "compute_m_atk_upgrade",
    "compute_m_ele",
    "compute_m_ammo",
    "compute_m_cs",
    "compute_m_crit",
    # probability
    "expected_stones_reroll_type",
    "expected_stones_reroll_value",
    "expected_stones_first_activation",
    "count_targets_on_gear",
    "count_low_tier_targets",
    "expected_cost_to_achieve_targets",
    # bidding_engine
    "GlobalBiddingEngine",
    "BidEntry",
    "generate_unified_ladder_report",
]