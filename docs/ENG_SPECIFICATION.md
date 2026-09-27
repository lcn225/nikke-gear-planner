# 📑 NIKKE 装备过载洗练与升级系统：底层物理事实、伤害公式与全局竞价排序白皮书

## 一、 底层伤害公式与乘区稀释物理事实 (Damage Formula)

根据官方解包与硬核测试验证，游戏内的最终伤害输出严格遵循以下多乘区非线性累乘耦合公式：
$$\text{Final Damage} = \text{Base Damage} \times \text{Major Modifiers} \times \text{Attribute Bonus} \times \text{Charge Multiplier} \times \text{Other Modifiers} \quad \text{}$$

### 1.1 核心子乘区分量定义

1. **基础伤害区（Base Damage）**：
   $$\text{Base Damage} = \left( \text{Character Base ATK} \times \left(1 + \sum \text{ATK Buffs}\right) - \text{Monster DEF} \right) \times \text{Skill Multiplier} \quad \text{[cite: 3]}$$
   * **加法稀释效应**：过载词条“攻击力增加”与战场主动战斗 Buff（丽塔、皇冠等常态提供 100%~150% 提升）在基础伤害乘区内呈**加算（Summated）关系**[cite: 3]。其实际相对提升率随主动 Buff 增强而衰减[cite: 3]。
2. **主要修正乘区（Major Modifiers - 加算灾难乘区）**：
   $$\text{Major Modifiers} = 1 + \text{Crit Damage Bonus} + \text{Core Hit Bonus} + \text{Distance Bonus} + \text{Full Burst Bonus} \quad \text{[cite: 3]}$$
   * **稀释事实**：核心打击（弱点补正 $+100\%$）[cite: 3]、距离加成（$+30\%$）[cite: 3] 与全爆发状态（$+50\%$）[cite: 3] 的基础之和高达 **$1.8$**，而暴击伤害的初始基础只有 **$0.5$**[cite: 3]。由于四者在同一区域内执行**加算**，导致暴击类增伤（暴击率、暴击伤害）在实战中受到毁灭性稀释，初始收益极其低下，同数值下被攻击力全方位立体式爆杀[cite: 3]。
3. **属性克制增伤区（Attribute Bonus - 独立物理优势）**：
   $$\text{Attribute Bonus} = 1.1 + E_{\text{OL\_Superior\_Code}} \quad \text{[cite: 3]}$$
   * **独立相乘事实**：“优越代码伤害增加”词条作为针对克制属性敌人的专属加成，在伤害公式中享有完全**独立相乘**的乘区地位[cite: 3]。由于基础克制加成仅为 $10\%$ ($0.1$)，该乘区基础分量仅为 $1.1$[cite: 3]。过载单槽最大 $26.36\%$ 的优越代码在克制环境下相对提升率高达 $26.36\% / 1.1 \approx 23.96\%$ ，抗稀释能力全词条池最高[cite: 3]。

---

## 二、 槽位判定机制与全量词条池概率 (Slot & Pool Mechanisms)

无论是头、身、手、足哪个部位，过载效果池完全一致，均包含全量 9 种词条。由于过载装备存在严苛的“同类词条互斥原则”，同一件装备上绝对不可能出现两条或以上完全相同的词条种类[cite: 3]。因此，随着词条被锁定，剩余槽位重新洗练时，该属性被永久剔除，其生成过程属于**无放回超几何选择**[cite: 3]。

### 2.1 槽位出现率

* **1号位（首栏）**：$100\%$ 概率赋予效果[cite: 3]。
* **2号位（次栏）**：$50\%$ 概率赋予效果，另外 $50\%$ 概率表现为空白（未开光）[cite: 3]。
* **3号位（末栏）**：$30\%$ 概率赋予效果，另外 $70\%$ 概率表现为空白（未开光）[cite: 3]。

### 2.2 独立出词率（无锁未去重状态）

当位置判定有词条时，各词条出现的抽取概率各自独立[cite: 3]：

* **暴击率、防御力、攻击力、优越代码增伤**：各占 **$10\%$** 出现概率[cite: 3]。
* **蓄力速度、命中率、蓄力伤害、暴击伤害、最大装弹数**：各占 **$12\%$** 出现概率[cite: 3]。

---

## 三、 锁词洗练与重设数值的追加门票与滚动刚性成本 (Locking Cost Scale)

### 3.1 瞬时门票费用（点击锁定扣除，一次性叠加）

* **从不锁 ➡️ 锁定第 1 个词条**：追加扣除 = **2 颗石头**。
* **从锁 1 ➡️ 锁定第 2 个词条**：追加扣除 = **3 颗石头**。
* *注：若连续锁定两条，累积门票成本为 2 + 3 = 5 颗石头。*

### 3.2 滚动洗练与重新设定数值费用（点击重置/重设数值消耗，单次滚动通用）

无论是点击【变更效果】洗种类，还是点击【重新设定数值】全量重刷 1~15 级档位（种类保持 100% 锁定继承），其单次滚动消耗完全受当前锁词数量支配：

* **当前锁定 0 个词条**：单次消耗 = **1 颗石头**。
* **当前锁定 1 个词条**：单次消耗 = **2 颗石头**。
* **当前锁定 2 个词条**：单次消耗 = **3 颗石头**。

---

## 四、 混合动作的纯数学期望成本函数模型 (Mathematical Expectation)

每一次消耗石头进行词条清洗或数值提纯，均严格建模为独立伯努利试验，首次成功所需的平均消耗量严格服从几何分布期望：$\mathbb{E}[N] = \frac{1}{P_{\text{success}}}$[cite: 3]。

### 4.1 无锁洗练（0 Locks）变更效果成本

设目标有效词条池大小为 $M$，总候选池为 9 种[cite: 3]。激活槽位总数 $A \in \{1, 2, 3\}$。激活状态的独立超几何分布概率为：$P(A=1)=0.35$，$P(A=2)=0.50$，$P(A=3)=0.15$[cite: 3]。
若装备当前已持有 $e$ 个有效词条（$e < 3$），欲通过无锁重构使有效词条数至少增加到 $e+1$ 的单次成功率 $P_{\text{success\_0}}$ 及几何期望成本为[cite: 3]：
$$P_{\text{success\_0}} = \sum_{a=1}^{3} P(A = a) \sum_{x=e+1}^{a} \frac{\binom{M}{x} \binom{9 - M}{a - x}}{\binom{9}{a}} \quad \implies \quad \mathbb{E}[C_{\text{wash\_0}}] = \frac{1}{P_{\text{success\_0}}} \quad \text{[cite: 3]}$$

### 4.2 锁一洗二（1 Lock）变更效果成本

锁 1 条后词条总池收缩至 $8$，剩余有效目标数变为 $M - 1$[cite: 3]。剩余两个随机槽位的激活概率分布为：$P(A_{\text{rem}}=1)=0.50$，$P(A_{\text{rem}}=2)=0.15$[cite: 3]。洗出至少 1 条新有效词条的期望总成本（含锁词门票）为[cite: 3]：
$$P_{\text{success\_1}} = \sum_{a_{\text{rem}}=1}^{2} P(A_{\text{rem}} = a_{\text{rem}}) \left( 1 - \frac{\binom{9 - M}{a_{\text{rem}}}}{\binom{8}{a_{\text{rem}}}} \right) \quad \implies \quad \mathbb{E}[C_{\text{wash\_1}}] = 2 \text{ (锁定门票)} + \frac{2}{P_{\text{success\_1}}} \quad \text{[cite: 3]}$$

### 4.3 锁二洗一（2 Locks）变更效果成本

仅剩唯一的 3 号槽位参与随机洗练，其能够提供新词条的概率上限被 3 号位自身激活概率（30%）锁死[cite: 3]。剩余候选池收缩至 $7$，剩余有效目标数为 $M - 2$[cite: 3]。期望总成本（含锁词门票）为[cite: 3]：
$$P_{\text{success\_2}} = 0.3 \times \frac{M - 2}{7} \quad \implies \quad \mathbb{E}[C_{\text{wash\_2}}] = 3 \text{ (锁定门票)} + \frac{3}{P_{\text{success\_2}}} \quad \text{[cite: 3]}$$

###### 4.4 渐进式数值洗练（数值提纯）硬核数学期望

对于种类已完美满足、但需要将数值提纯至 Tier 11+（蓝/黑词，单格客观出现概率 $P_{\text{high}} = 5\%$）的装备，采用“渐进式锁定清洗”方案，其单步几何分布叠加成本在数学上严格恒等于：

* **持有 1 条有效词条 ($k = 1$)**：无需锁定，直接单槽重洗。
  $$\mathbb{E}[C] = \frac{1}{0.05} \times 1 = \mathbf{20.00 \text{ 颗}}$$
* **持有 2 条有效词条 ($k = 2$)**：洗双槽中至少一槽达到 Tier 11+ ➡️ 锁定该槽（付 2 颗门票） ➡️ 单洗最后一槽达到 Tier 11+。
  $$\mathbb{E}[C] = \frac{1}{1 - 0.95^2} \times 1 + 2 + \frac{2}{0.05} = 10.26 + 2 + 40 = \mathbf{52.26 \text{ 颗}}$$
* **持有 3 条有效词条 ($k = 3$)**：洗三槽中至少一槽达到 Tier 11+ ➡️ 锁一洗二 ➡️ 锁二洗一。
  $$\mathbb{E}[C] = \frac{1}{1 - 0.95^3} \times 1 + \left(2 + \frac{2}{1 - 0.95^2}\right) + \left(3 + \frac{3}{0.05}\right) = 7.01 + 22.51 + 63 = \mathbf{92.52 \text{ 颗}}$$

---

## 五、 装备升级的影子价格与等效换算 (Shadow Pricing)

为消除跨资源壁垒，引入宏观经济学中的影子价格（Shadow Pricing）换算体系，将只消耗信用点的“强化升级动作”无缝映射至石头消耗数轴上[cite: 3]。

### 5.1 信用点到重塑石头的影子价格系数 $\lambda$

在全勤活跃的后期服务器环境下，信用点与石头的相对价值稀缺度均衡系数定义为[cite: 3]：
$$\lambda = \frac{1.5 \times 10^6 \text{ Credits}}{1 \text{ Custom Module}} \quad \text{[cite: 3]}$$

### 5.2 强化阶段等效成本与线性物理面板增幅

* **强化一整件 T10 装备至满级所需的 $2.4\text{M}$ 信用点 即可被折算为等效石头成本[cite: 3]**：
  `Lv 0 ➡️ Lv 1`: 150k金币 ($0.10$石)；`Lv 1 ➡️ Lv 2`: 250k金币 ($0.17$石)；`Lv 2 ➡️ Lv 3`: 400k金币 ($0.27$石)；`Lv 3 ➡️ Lv 4`: 650k金币 ($0.43$石)；`Lv 4 ➡️ Lv 5`: 950k金币 ($0.63$石)[cite: 3]。
* **部位核心增益壁垒与绝对面板增幅（基于后期主C 35,000 基础裸攻击）[cite: 3]**：
  - **头部装备（Helmet）**：物理增益全集中于攻击力。每级强化增加固定物理攻击力 $\Delta ATK_{\text{head}} = 900$ 点[cite: 3]。
  - **手部装备（Gloves）**：提供次要攻击力。每级强化增加固定物理攻击力 $\Delta ATK_{\text{hand}} = 440$ 点[cite: 3]。
  - **身体与足部（Chest & Boots）**：仅提供物理防御与生命值，对主输出角色（Attacker）带来的输出边际收益贡献严格恒等于 **$0.00\%$**[cite: 3]。

---

## 六、 累乘相对提升率收益函数与全局大排队竞价机制

排序引擎 $\mathcal{A}_{\text{ROI}}$ 对全队妮姬的每一件装备执行全操作空间（开光、洗种类、洗数值、强化升级）的遍历，核心公式如下[cite: 3]：
$$\text{ROI} = \frac{B(S \to S')}{\Delta \text{Cost (等效石头)}} = \frac{\frac{\mathcal{F}(S')}{\mathcal{F}(S)} - 1}{\Delta \text{Cost}} \quad \text{[cite: 3]}$$

###### 6.1 各特殊乘区非线性相对收益函数

1. **攻击面板升级增幅函数**：
   $$\mathcal{M}_{\text{ATK\_upgrade}}(v \to v+1) = \frac{ATK_{\text{current}} + \Delta ATK_{\text{part}}}{ATK_{\text{current}}} \quad \text{[cite: 3]}$$
2. **最大装弹数相对收益改善函数（发射-换弹时间占空比改进）**：
   $$\mathcal{M}_{\text{Ammo}} = \frac{C_{\text{base}}(1 + Ammo_{\text{OL\_new}}) + F \cdot R}{C_{\text{base}}(1 + Ammo_{\text{OL\_new}}) + F \cdot R \cdot \left(\frac{1 + Ammo_{\text{OL\_new}}}{1 + Ammo_{\text{OL\_old}}}\right)} \dots \quad \text{[cite: 3]}$$
   * **阿妮斯：闪耀夏日反向剧毒惩罚函数**：因其机制严苛依赖打空弹夹的最后一发，弹夹增加赋予陡峭的负收益，彻底锁死排队胜出可能[cite: 3]：
     $$\mathcal{M}_{\text{Ammo\_Anis}} = \frac{1.0}{1.0 + 10.0 \times \Delta Ammo_{\text{OL}}} \quad \text{[cite: 3]}$$
3. **蓄力速度阶梯断层增幅函数（秒蓄门槛）**：
   对爱丽丝（补偿阈值 $7.7\%$）与小红帽（补偿阈值 $10.0\%$）在跨越临界点前提供极高增幅，跨越后边际相对收益瞬间归零[cite: 3]：
   $$\mathcal{M}_{\text{CS}}(CS_{\text{OL}}) = \frac{1.0}{0.4727 - 1.5 \times \min(0.077, CS_{\text{OL}})} \quad \text{[cite: 3]}$$

### 6.2 暴击/暴伤乘区分量精确定义

拒绝任何无源头系数与主观强行压低。严格还原补正区基础物理常量之和（$1.0 + 弱点1.0 + 距离0.3 + 全爆裂0.5 = 2.8$）的硬核事实，暴击乘区相对增幅函数严格遵循以下公式进行全量稀释结算：
$$\mathcal{M}_{\text{Crit}} = \frac{2.8 + (\text{基础暴击率} + \text{过载暴击率}\%) \times (0.5 + \text{过载暴击伤害}\%)}{2.8 + \text{基础暴击率} \times 0.5}$$