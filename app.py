"""
NIKKE 装备优化规划器 — Streamlit 图形界面

功能：
- 上传 cn_collect.json（账号实际装备表，格式见 input/数据说明.md）
- 输入资源库存（石头 + 信用点）
- 运行全局竞价计算
- 展示天梯表格 + ROI柱状图 + 统计信息
- 筛选操作类型（洗词条/洗数值/洗词条+洗数值/升级/开光）
- 导出 CSV
- 导出纯文本执行清单
"""

import streamlit as st
import json
import os
import pandas as pd
from datetime import datetime
from typing import List

from history_manager import (
    save_history, list_history, load_history, delete_history, resolve_replay,
)
from models.targets import panel_directive_text, snapshot_targets

# 设置页面
st.set_page_config(
    page_title="NIKKE Gear Planner",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 导入后端
from ui_backend import (
    load_roster_from_json_content,
    run_calculation,
    build_character_dataframe,
    build_character_detail,
    format_bids_to_dataframe,
    get_bid_statistics,
)


# ────────────────────────────────────────────────────────────
# 自定义 CSS
# ────────────────────────────────────────────────────────────

st.markdown("""
<style>
    .stDataFrame { font-size: 14px; }
    .warning-red { color: #ff4b4b; font-weight: bold; }
    .warning-yellow { color: #ffa500; font-weight: bold; }
</style>
""", unsafe_allow_html=True)


# ────────────────────────────────────────────────────────────
# 标题
# ────────────────────────────────────────────────────────────

st.title("⚙️ NIKKE 装备过载规划器")
st.caption("基于五大乘区伤害模型 + 方案级全局竞价算法")


# ────────────────────────────────────────────────────────────
# 侧边栏：输入
# ────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("📤 数据输入")
    
    uploaded_file = st.file_uploader(
        "上传 cn_collect.json",
        type=["json"],
        help="账号实际装备表（游戏端导出/OCR 采集），格式见 input/数据说明.md"
    )

    # 养成目标取自 data/targets_parsed.json（全服通用，不随账号走），
    # 所以上传的文件里没有它 —— 目标按模式现取。
    targets_mode = st.radio(
        "养成目标模式",
        options=["PVE", "PVP"],
        horizontal=True,
        help="取自 data/targets_parsed.json。PVP 与 PVE 的目标词条差别很大"
             "（例如灰姑娘 PVE 要优越、PVP 要暴击率）。",
    )

    st.divider()
    
    st.header("💰 资源库存")
    
    stones = st.number_input(
        "自定义模块（石头）",
        min_value=0,
        value=100,
        step=10,
        help="当前持有的企业重塑模组数量"
    )
    
    credits = st.number_input(
        "信用点（万）",
        min_value=0,
        value=500,
        step=50,
        help="当前持有的信用点（单位：万）"
    ) * 10000
    
    st.divider()
    
    st.header("⚙️ 显示配置")
    
    top_n = st.slider(
        "显示 Top N",
        min_value=5,
        max_value=100,
        value=20,
        step=5
    )
    
    st.divider()
    
    st.header("🔍 筛选条件")
    
    action_types = st.multiselect(
        "显示操作类型",
        options=["洗词条", "洗数值", "洗词条+洗数值", "升级", "开光"],
        default=["洗词条", "洗数值", "洗词条+洗数值", "升级", "开光"],
        help="只显示选中的操作类型"
    )
    
    st.divider()
    
    run_btn = st.button(
        "🚀 运行计算",
        type="primary",
        use_container_width=True
    )

    st.divider()

    # ── 历史记录 ──
    # 每次跑计算都自动存一份，约 900KB。所以这里既要有加载也要有删除，
    # 并显示总体积 —— 否则目录会一直长而看不见。
    with st.expander("📜 历史记录"):
        history_list = list_history()
        if history_list:
            total_mb = sum(h["size"] for h in history_list) / 1024 / 1024
            st.caption(f"共 {len(history_list)} 份，占 {total_mb:.1f} MB（每份约 0.9 MB）")
            for h in history_list:
                col_load, col_del = st.columns([6, 1])
                with col_load:
                    # 模式要写出来：PVE / PVP 的目标词条差别很大，同一份名册
                    # 会算出两份完全不同的榜，凭时间戳认不出来。
                    mode_tag = f"{h['mode']}  |  " if h["mode"] else ""
                    # 旧记录（R1b 之前存的）没有名册快照，点开只有明细天梯
                    replay_tag = "" if h["has_snapshot"] else "  |  ⚠️ 无角色榜快照"
                    label = (f"{h['timestamp']}  |  {mode_tag}{h['stones']}石  "
                             f"|  {h['total_bids']}条{replay_tag}")
                    # key 必须区分加载与删除，否则 Streamlit 会当成同一个控件
                    if st.button(label, key=f"load::{h['filename']}",
                                 use_container_width=True):
                        st.session_state.history_loaded = True
                        st.session_state.history_path = h["filepath"]
                        st.session_state.history_data = load_history(h["filepath"])
                        st.rerun()
                with col_del:
                    if st.button("✕", key=f"del::{h['filename']}",
                                 help="删除这条历史记录"):
                        if delete_history(h["filepath"]):
                            st.toast(f"已删除 {h['timestamp']}") \
                                if hasattr(st, "toast") else None
                        st.rerun()
        else:
            st.caption("暂无历史记录")


# ────────────────────────────────────────────────────────────
# 状态管理
# ────────────────────────────────────────────────────────────

if "bids" not in st.session_state:
    st.session_state.bids = None
if "characters" not in st.session_state:
    st.session_state.characters = None
if "stats" not in st.session_state:
    st.session_state.stats = None


# ────────────────────────────────────────────────────────────
# 核心逻辑：运行计算
# ────────────────────────────────────────────────────────────

if run_btn:
    if uploaded_file is None:
        st.error("⚠️ 请先上传 cn_collect.json 文件（账号实际装备表，格式见 input/数据说明.md）")
    else:
        try:
            content = uploaded_file.read()

            with st.status("📥 正在加载阵容数据...", expanded=True) as status:
                roster = load_roster_from_json_content(content, mode=targets_mode)
                characters = roster.characters
                status.update(label=f"✅ 已加载 {len(characters)} 个角色", state="complete")

            # 加载报告：数据异常与「目标词条未接入」必须显示出来。
            # 静默吞掉会让一份只剩「升级」类竞价的残缺天梯看起来像完整结果。
            if roster.issues:
                st.warning("⚠️ 数据异常（留空 + 报警，未兜底）：\n" + "\n".join(f"- {i}" for i in roster.issues))
            if not roster.targets_attached:
                st.warning(
                    "⛔ 目标词条未接入：洗词条 / 洗数值 / 开光 均为 0 条，"
                    "本结果只剩「升级」类竞价，**不代表已毕业**。"
                    "请确认 data/targets_parsed.json（随仓库分发的快照）存在且未被改动。"
                )

            with st.status("🧮 正在运行竞价引擎...", expanded=True) as status:
                bids, unmet_primary = run_calculation(characters, stones, credits)
                status.update(label=f"✅ 生成 {len(bids)} 条竞价方案", state="complete")

            st.session_state.bids = bids
            st.session_state.unmet_primary = unmet_primary
            st.session_state.characters = characters
            st.session_state.stats = get_bid_statistics(bids)
            st.session_state.stones = stones
            st.session_state.credits = credits
            # 本轮名册与门禁结果的出处。历史记录不含名册，加载历史时名册只能「借」——
            # 仅当那份历史就是本轮自己存出去的文件时才算同源（见下方加载分支）。
            # 路径先清空再在保存成功后写入：保存失败时若留着上一轮的路径，
            # 用户加载上一轮那份文件会被误判成同源，配到本轮的竞价上。
            st.session_state.last_run_history_path = None
            st.session_state.last_run_characters = characters
            st.session_state.last_run_unmet_primary = unmet_primary
            # 本轮是现算的，不是回放 —— 把上一次加载历史留下的标注清掉，
            # 否则「本条历史是 PVP 模式」这类说明会粘在现算结果上。
            st.session_state.history_mode = None
            st.session_state.history_unmatched = []
            st.session_state.history_snapshot_error = None

            st.success("✅ 计算完成！")

            # 自动保存历史：竞价明细 + 名册/目标/门禁快照，凑成一份可回放的记录
            # （见 history_manager 模块开头）。角色榜的输入全在里面，所以冷启动
            # 直接加载这条历史也能重建出一模一样的榜。
            try:
                saved_path = save_history(
                    bids, stones, credits, len(characters),
                    mode=targets_mode,
                    roster=characters,
                    targets=snapshot_targets([c.name for c in characters], targets_mode),
                    unmet_primary=unmet_primary,
                )
                st.session_state.last_run_history_path = saved_path
            except Exception as e:
                # 保存失败必须吭声。以前这里把整个 save_history 包进 try，
                # 失败时会照样打印「已自动保存」—— 那句话是假的，
                # 而且这条路径还决定了加载历史时能不能借用名册。
                st.warning(f"⚠️ 历史记录保存失败，本次结果未落盘：{e}")
            else:
                try:
                    st.toast("✅ 已自动保存历史记录", icon="💾")
                except Exception:
                    # st.toast 在 Streamlit <1.30 不可用，降级为 success
                    st.success("💾 已自动保存历史记录")
            
        except json.JSONDecodeError as e:
            st.error(f"❌ JSON 解析失败: {e}")
        except Exception as e:
            st.error(f"❌ 计算出错: {e}")
            st.exception(e)


# ────────────────────────────────────────────────────────────
# 导出执行清单函数
# ────────────────────────────────────────────────────────────

# ── 角色榜渲染 + 点击展开 ──



def _supports_row_selection() -> bool:
    """
    st.dataframe 的点选（on_select）是 Streamlit 1.35 才有的。
    版本读不出来时按「不支持」处理 —— 退化成下拉框总比整页崩强。
    """
    try:
        major, minor = (int(x) for x in st.__version__.split(".")[:2])
        return (major, minor) >= (1, 35)
    except Exception:
        return False


def _char_column_config() -> dict:
    return {
        "顺位": st.column_config.NumberColumn(format="%d"),
        "角色": st.column_config.TextColumn(width="medium"),
        "档位": st.column_config.TextColumn(help="T0 最好，Tcg = 仓管"),
        "下一步": st.column_config.TextColumn(width="large"),
        "成本(石)": st.column_config.NumberColumn(format="%.2f"),
        "ROI": st.column_config.NumberColumn(format="%.4f"),
        "毕业进度": st.column_config.TextColumn(width="medium"),
        "候选数": st.column_config.NumberColumn(
            help="该角色有多少条候选动作，这里只显示最优的一条，点行展开看全部"),
        "gated": None,     # 内部标记，已并入「下一步」的 ⏸ 前缀
    }


def render_character_ladder(char_df) -> str | None:
    """渲染角色榜表格，返回被点选的角色名（没选则 None）。"""
    if _supports_row_selection():
        try:
            event = st.dataframe(
                char_df,
                on_select="rerun",
                selection_mode="single-row",
                column_config=_char_column_config(),
                hide_index=True,
                use_container_width=True,
            )
            rows = getattr(getattr(event, "selection", None), "rows", None)
            if rows:
                return str(char_df.iloc[rows[0]]["角色"])
            st.caption("👆 点击任意一行，展开该角色的完整详情。")
            return None
        except TypeError:
            # 版本号看着够但 API 不认（厂商分支/降级安装），落到下拉框
            pass

    # 老版本 Streamlit：没有点选，用下拉框代替
    st.caption("当前 Streamlit 版本不支持表格点选，改用下拉框展开：")
    options = ["（不展开）"] + char_df["角色"].tolist()
    choice = st.selectbox("展开某个角色的详情", options=options, label_visibility="collapsed")
    return None if choice == "（不展开）" else choice


def render_character_detail(detail: dict, stones_held: int = 0):
    """角色的展开视图：核心词条达成 + 毕业面板 + 该角色的全部候选动作。"""
    if not detail:
        st.warning("⚠️ 找不到该角色的详情（历史记录模式下没有角色快照）。")
        return

    name = detail["name"]
    tier = detail["tier"]
    st.markdown(f"#### 🔍 {name}" + (f" · T{tier}" if tier else ""))

    unmet = detail["unmet"]
    if unmet:
        st.warning("🚧 **核心词条还没铺开**：" + "、".join(unmet)
                   + "　—　标 ⏸ 的条目属于副目标，建议先做核心词条。")
    elif detail["primary"]:
        st.success("✅ 核心词条已达成。")

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("**核心词条达成情况**")
        if not detail["primary"]:
            st.caption("该角色在推荐表里被判为「无需词条」—— 攻略认为词条只影响战力，"
                       "不影响它的作用。")
        else:
            st.dataframe(
                [{"词条": x["buff"], "已有": x["have"], "下限": x["need"],
                  "状态": "✅" if x["done"] else "❌"} for x in detail["primary"]],
                hide_index=True, use_container_width=True,
            )

    with c2:
        st.markdown("**毕业面板进度**")
        if detail["panel"]:
            st.dataframe(
                [{"词条": x["buff"], "当前": f"{x['have']:.1f}%",
                  "目标": f"{x['want']:.0f}%",
                  "缺口": "—" if x["done"] else f"{x['gap']:.1f}%",
                  "状态": "✅" if x["done"] else "差"} for x in detail["panel"]],
                hide_index=True, use_container_width=True,
            )
        elif detail["panel_directives"]:
            st.caption("毕业方向：" + panel_directive_text(detail["panel_directives"]))
        else:
            st.caption("推荐表未给出该角色的数值面板。")

    st.markdown(f"**全部候选动作（{detail['n_actions']} 条，按顺位排序）**")
    acts = detail["actions"]
    if not acts:
        st.caption("该角色当前没有可算的候选动作。")
    else:
        adf = format_bids_to_dataframe(acts, stones_held=stones_held, top_n=0)
        st.dataframe(adf, hide_index=True, use_container_width=True,
                     height=min(420, 40 + 35 * len(adf)))


def generate_execution_plan(bids: List, stones: int, credits: int, top_n: int = 30) -> str:
    """生成纯文本执行清单"""
    lines = []
    lines.append("=" * 60)
    lines.append("  NIKKE 装备优化执行清单")
    lines.append(f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"  库存: {stones} 石 | {credits/10000:.0f} 万 信用点")
    lines.append("=" * 60)
    lines.append("")
    
    cumulative_cost = 0.0
    display_bids = bids[:top_n]
    
    for i, bid in enumerate(display_bids, 1):
        cumulative_cost += bid.equivalent_cost
        
        # 操作类型图标
        icon_map = {
            "升级": "🟢",
            "开光": "🆕",
            "洗词条": "🟡",
            "洗数值": "🟠",
            "洗词条+洗数值": "🟣"
        }
        icon = icon_map.get(bid.action_type, "🔵")
        
        lines.append(f"{icon} 【第 {i} 步】{bid.character_name} | {bid.gear_slot}")
        lines.append(f"  详情: {bid.action_detail}")
        lines.append(f"  成本: {bid.resource_desc}")
        lines.append(f"  收益: +{bid.expected_damage_gain*100:.2f}%  |  ROI: {bid.roi:.4f}")
        lines.append(f"  累计消耗: {cumulative_cost:.2f} 石")
        lines.append("")
    
    lines.append("=" * 60)
    remaining = stones - cumulative_cost
    lines.append(f"  📊 累计消耗: {cumulative_cost:.2f} / {stones} 石  (剩余: {remaining:.2f} 石)")
    
    if remaining < 0:
        lines.append("  ⚠️ 当前资源不足以执行全部推荐方案，请优先执行前几项")
    elif remaining < 10:
        lines.append("  ⚠️ 剩余资源较少，建议谨慎规划后续步骤")
    else:
        lines.append("  ✅ 资源充足，可按顺序依次执行")
    
    lines.append("=" * 60)
    
    return "\n".join(lines)


# ────────────────────────────────────────────────────────────
# 结果展示
# ────────────────────────────────────────────────────────────

# 检测是否加载了历史记录
if st.session_state.get("history_loaded") and st.session_state.get("history_data"):
    data = st.session_state.history_data
    # 从历史数据重建 bids
    from engine.bidding_engine import BidEntry
    bids = []
    for b in data["bids"]:
        bid = BidEntry(
            priority=b["priority"],
            character_name=b["character_name"],
            gear_slot=b["gear_slot"],
            action_type=b["action_type"],
            target_set=set(b["target_set"]) if b["target_set"] else set(),
            equivalent_cost=b["equivalent_cost"],
            expected_damage_gain=b["expected_damage_gain"],
            roi=b["roi"],
            action_detail=b["action_detail"],
            resource_desc=b["resource_desc"],
            # 旧历史文件没有这几个字段，用 .get() 兜底而不是让整条历史读不出来。
            # 缺了它们只是 ⏸ 标记和档位列显示不出来，不至于报错。
            gated=b.get("gated", False),
            tier=b.get("tier", ""),
            tier_weight=b.get("tier_weight", 1.0),
            sort_score=b.get("sort_score", 0.0),
        )
        bids.append(bid)
    stats = get_bid_statistics(bids)
    # 覆盖 session_state
    st.session_state.bids = bids
    st.session_state.stats = stats
    st.session_state.stones = data["stones"]
    st.session_state.credits = data["credits"]
    # 角色榜是 f(名册, 竞价, 门禁) 三输入的函数，三者必须同源（R1a 的教训：
    # 旧名册配新竞价会渲染出一张看着正常、实际错配的表）。上面换掉的只有
    # bids，名册与门禁从哪来由 resolve_replay 定 —— 那段决策是纯逻辑，
    # 放在 history_manager 里，WSL 侧测得动。
    replay = resolve_replay(
        data,
        history_path=st.session_state.get("history_path"),
        last_run_path=st.session_state.get("last_run_history_path"),
        last_run_characters=st.session_state.get("last_run_characters"),
        last_run_unmet_primary=st.session_state.get("last_run_unmet_primary"),
    )
    st.session_state.characters = replay.characters
    st.session_state.unmet_primary = replay.unmet_primary
    # 这三项是「本条榜从哪来」的标注，只有真读到快照时才有值。
    # 不覆盖的话，上一条历史的模式说明 / 读取错误会粘在下一条上。
    st.session_state.history_mode = replay.mode or None
    st.session_state.history_unmatched = replay.unmatched_targets
    # 错误要写进 session_state —— 紧跟着就 st.rerun()，此刻画出来的活不过重跑。
    st.session_state.history_snapshot_error = (
        f"⚠️ 这份历史记录的快照读不出来，角色培养榜无法重建：{replay.error}"
        if replay.error else None)
    st.session_state.history_loaded = False  # 避免重复加载
    st.toast(f"📂 已加载历史记录: {data['timestamp']}", icon="📂") if hasattr(st, 'toast') else st.success(f"📂 已加载历史记录: {data['timestamp']}")
    st.rerun()

if st.session_state.bids is not None:
    bids = st.session_state.bids
    stats = st.session_state.stats
    
    # 应用筛选
    if action_types:
        filtered_bids = [b for b in bids if b.action_type in action_types]
    else:
        filtered_bids = bids
    
    if not filtered_bids:
        st.warning("⚠️ 当前筛选条件下没有匹配的方案，请调整筛选条件。")
        st.stop()
    
    # 重新统计
    filtered_stats = get_bid_statistics(filtered_bids)
    
    # 使用 session_state 的值（支持历史加载覆盖）
    display_stones = st.session_state.get("stones", stones)
    display_credits = st.session_state.get("credits", credits)

    # ── 统计卡片 ──
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("总方案数 (筛选后)", filtered_stats["total"])
    with col2:
        st.metric("最高 ROI", f"{filtered_stats['top_roi']:.4f}")
    with col3:
        st.metric("石头库存", display_stones)
    with col4:
        st.metric("信用点库存", f"{display_credits/10000:.0f}万")
    
    # ── 类型分布 ──
    if filtered_stats["types"]:
        type_labels = []
        type_values = []
        icon_map = {"升级": "🟢", "开光": "🆕", "洗词条": "🟡", "洗数值": "🟠", "洗词条+洗数值": "🟣"}
        for t, c in filtered_stats["types"].items():
            type_labels.append(f"{icon_map.get(t, '🔵')}{t}")
            type_values.append(c)
        st.caption(" | ".join([f"{label}: {v}" for label, v in zip(type_labels, type_values)]))
    
    st.divider()

    # ── 角色培养榜（主视图）──
    # 一行 = 一个角色的下一步。用户的问题是「我现在该把资源用到哪」，
    # 答案是**某个角色的某件事**，不是「第 303 顺位那条洗练」。
    st.subheader("🏆 角色培养榜")
    st.caption(
        "一行 = 一个角色的**下一步**。排序：档位优先（T0 是永久保质期角色，"
        "投进去的每分资源都有回报），档内按该角色最优动作的 ROI。"
        "已毕业的角色不列出。"
    )

    # 回放的历史：模式要与侧边栏当前选的一致才不让人误会。榜是按记录自带的
    # 那份目标（历史当时那个模式）重建的，这里只是把差异说出来。
    hist_mode = st.session_state.get("history_mode")
    if hist_mode and hist_mode != targets_mode:
        st.caption(
            f"📂 这条历史由 **{hist_mode}** 模式的养成目标算出，"
            f"与侧边栏当前选的 {targets_mode} 不同 —— 下面是历史当时的结果。"
        )

    saved_characters = st.session_state.get("characters")
    if not saved_characters:
        load_error = st.session_state.get("history_snapshot_error")
        if load_error:
            st.error(load_error)
        else:
            # 没有名册**不能**把空名册喂给角色榜 —— 它会显示「所有角色已毕业」，
            # 而那句话是假的。宁可显示一段说明。
            st.info(
                "📂 这份历史记录是「只存竞价明细」的旧格式，没有角色装备快照，"
                "所以无法生成角色培养榜。重新上传 cn_collect.json 并点「运行计算」，"
                "存出的新记录会自带快照，之后加载都能看到角色榜。"
            )
        char_df = None
    else:
        char_df = build_character_dataframe(
            saved_characters,
            bids,                                # 用全量 bids，不受操作类型筛选影响
            st.session_state.get("unmet_primary") or {},
            top_n=top_n,
        )
        replay_unmatched = st.session_state.get("history_unmatched") or []
        if replay_unmatched:
            st.caption(
                f"⚠️ 快照里这 {len(replay_unmatched)} 个角色没有养成目标"
                f"（与历史当时运行一致，推荐表查无此人）："
                f"{'、'.join(replay_unmatched)}"
            )
    if char_df is not None and char_df.empty:
        st.info("🎉 所有角色已毕业，暂无培养动作。")
    elif char_df is not None:
        if char_df["下一步"].astype(str).str.startswith("⏸").any():
            st.caption("⏸ = 该角色核心词条还没铺开，这条属于副目标，建议先做它的核心词条。")

        picked = render_character_ladder(char_df)

        if picked:
            detail = build_character_detail(
                picked, saved_characters, bids,
                st.session_state.get("unmet_primary") or {})
            render_character_detail(detail, stones_held=display_stones)

    st.divider()

    # ── 明细天梯（次视图）──
    st.subheader("📋 明细竞价天梯")
    st.caption("每一条候选动作。角色榜是它的「按角色聚合」视图。")

    df = format_bids_to_dataframe(filtered_bids, stones_held=display_stones, top_n=top_n)
    
    if not df.empty:
        st.dataframe(
            df,
            column_config={
                "顺位": st.column_config.NumberColumn(format="%d"),
                "角色": st.column_config.TextColumn(),
                "部位": st.column_config.TextColumn(),
                "操作": st.column_config.TextColumn(),
                "目标组合": st.column_config.TextColumn(),
                "等效成本(石)": st.column_config.NumberColumn(format="%.2f"),
                "预期增幅": st.column_config.TextColumn(),
                "ROI": st.column_config.NumberColumn(format="%.4f"),
                "警告": st.column_config.TextColumn(),
                "详情": st.column_config.TextColumn(width="large"),
            },
            hide_index=True,
            use_container_width=True,
            height=min(800, 35 * len(df) + 40)
        )
    
    # ── ROI 柱状图 ──
    st.subheader("📊 TOP 20 ROI 分布")
    chart_df = df[["角色", "目标组合", "ROI"]].head(20).copy()
    chart_df["标签"] = chart_df["角色"] + "\n" + chart_df["目标组合"].str[:15]
    st.bar_chart(chart_df.set_index("标签")["ROI"])
    
    # ── 导出区域 ──
    st.divider()
    
    col_export1, col_export2, col_export3 = st.columns(3)
    
    with col_export1:
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 导出 CSV",
            data=csv,
            file_name="gear_planner_results.csv",
            mime="text/csv",
            use_container_width=True
        )
    
    with col_export2:
        plan_text = generate_execution_plan(
            filtered_bids,
            display_stones,
            display_credits,
            top_n=top_n
        )
        st.download_button(
            label="📋 导出执行清单",
            data=plan_text.encode('utf-8'),
            file_name="execution_plan.txt",
            mime="text/plain",
            use_container_width=True
        )
    
    with col_export3:
        # 预览执行清单（点击后展开）
        with st.expander("📄 预览执行清单"):
            st.code(plan_text, language="text")
    
    # ── 公式说明 ──
    st.caption("💡 公式: ROI = 期望收益 / 期望成本  |  基于五大乘区累乘模型")


# ────────────────────────────────────────────────────────────
# 初始状态：引导信息
# ────────────────────────────────────────────────────────────

else:
    st.info("👈 请在左侧上传 `cn_collect.json`，设置资源库存后点击「运行计算」")

    st.markdown("""
    ### 📖 快速指南

    1. **准备数据**：导出账号实际装备表 `cn_collect.json`（格式见 `input/数据说明.md`）
    2. **上传文件**：点击侧边栏的「上传 cn_collect.json」
    3. **设置资源**：输入你当前持有的石头和信用点数量
    4. **运行计算**：点击「🚀 运行计算」，等待结果
    
    ---
    
    ### 🧠 算法原理
    
    - **五大乘区**：(ATK) × (ELE) × (Ammo占空比) × (CS秒蓄门槛) × (Crit)
    - **方案级竞价**：每个目标是「达成某个词条组合」，而非单次洗练
    - **ROI 排序**：所有操作（开光/升级/洗练）在同一公式下竞争
    
    ---
    
    ### 📤 导出功能
    
    - **CSV**：完整数据，可用 Excel 打开二次分析
    - **执行清单**：纯文本行动清单，按优先级排序，含累计消耗
    """)