"""
控制台输出的编码降级层：让 emoji 在 GBK 环境里既不炸、也不静默。

**要解决的问题**：中文 Windows 上，stdout 被**重定向或管道捕获**时编码是 GBK
（cp936），`print("✅ 通过")` 直接抛 UnicodeEncodeError。真实控制台窗口反而不受影响
—— Python 在 Windows 控制台上走 WriteConsoleW，编码报 utf-8（PEP 528），
所以现象是「手敲没事、一 pipe 就炸」。

本仓库正栽在这上面：测试运行器的异常处理路径里有一句 `print("❌ … 失败")`，
于是一条测试失败 → UnicodeEncodeError → 异常从 except 块里逃出去 → **整轮中止**。
那个分支本来的立意恰恰是「一条失败不终止整轮」，结果它在 Windows 管道下
自己造出了一个 fail-fast，还比原来更隐蔽：后面没跑的测试看不到任何痕迹。

**为什么不是把 stdout 改成 UTF-8**：GBK 控制台会把 UTF-8 字节按 GBK 渲染成乱码
—— 从「响亮地崩」换成「安静地显错」，与本项目「不把不知道伪装成知道」的铁律相反。

**做法**：注册一个 codec 错误处理器，只在**真的编不出来**时把字符换成 ASCII。
UTF-8 环境（Linux/WSL、Windows 真实控制台）里编码永远不失败，emoji 一个不变 ——
所以这不是「统一改文案」，是「编不出来才降级」。

降级规则分三档：

1. **状态标记**（✅❌⏭⚠⏸🚧）→ 等义 ASCII 标记，降级后仍要一眼分得清。
2. **有语义的符号**（− ↔ ✕ ² ³）→ 等义 ASCII，不当占位符丢掉。
3. **其余**（装饰性 emoji 🏆📊🔵、GBK 覆盖外的汉字）→ 按类别降级成看得见的
   占位符：符号类 `[*]`，文字类 `?`。挑这个规则是因为装饰性图标的含义
   已经写在它旁边的文字里（表格里 `🔵 开光` 的「开光」就在图标右边），
   而**看得见的**占位符不会让一个字符悄无声息地消失。

用法：在进程入口调一次 `install_console_fallback()`。
"""

import codecs
import sys
import unicodedata

# 处理器在 codecs 里的注册名。测试直接用它来验降级结果，所以是公开的。
HANDLER_NAME = "nikke_console"

# ── 第 1、2 档：编不出来时换成语义等价的 ASCII ─────────────────────
_FALLBACK = {
    # 状态标记：降级后仍然要一眼分得清是哪一种
    "✅": "[OK]",
    "❌": "[FAIL]",
    "⏭": "[SKIP]",
    "⚠": "[WARN]",
    "⛔": "[STOP]",
    "⏸": "[HOLD]",      # 主目标未达成的门禁标记
    "🚧": "[TODO]",     # 待突破
    "🔴": "[WARN]",     # 库存不足

    # 有语义的符号。它们出现在公式、回溯源码行或报告正文里，丢掉会改变读法，
    # 所以给等义 ASCII 而不是占位符。
    "−": "-",           # 减号（GBK 有 — 和 －，没有这个 U+2212）
    "↔": "<->",
    "✕": "x",
    "²": "^2",
    "³": "^3",
}

# 变体选择符：本身不可见，跟在 emoji 后面选择字形。写成转义而不是字面量 ——
# 字面量在编辑器里是隐形的，谁改坏了都看不出来。
_VARIATION_SELECTORS = "\ufe0e\ufe0f"


def _ascii_fallback(exc):
    """UnicodeEncodeError 处理器：把编不出来的字符换成语义等价的 ASCII。"""
    if not isinstance(exc, UnicodeEncodeError):
        raise exc

    text = exc.object
    start, end = exc.start, exc.end
    ch = text[start]

    # 一并吞掉紧随其后的变体选择符。不吞的话 ⏭️ = U+23ED + U+FE0F 会被处理两次，
    # 输出成 "[SKIP][*]" —— 多出来的那个尾巴正是此类降级最容易出的错。
    while end < len(text) and text[end] in _VARIATION_SELECTORS:
        end += 1

    if ch in _VARIATION_SELECTORS:
        return "", end          # 孤立的选择符：不可见，直接丢掉

    if ch in _FALLBACK:
        return _FALLBACK[ch], end

    # 第 3 档：按 Unicode 大类分。符号/emoji（S*）用占位符，文字类用 "?"。
    # 用 unicodedata 而不是写死码点区间 —— 新增的 emoji 不必回来登记。
    placeholder = "[*]" if unicodedata.category(ch).startswith("S") else "?"
    return placeholder, end


def install_console_fallback() -> None:
    """
    给本次进程的 stdout / stderr 装上编码降级。幂等，可重复调用。

    只影响「编不出来」这条路径，UTF-8 环境下输出与安装前逐字节相同。
    """
    try:
        codecs.lookup_error(HANDLER_NAME)
    except LookupError:
        codecs.register_error(HANDLER_NAME, _ascii_fallback)

    for stream in (sys.stdout, sys.stderr):
        # 被替换过的流（某些捕获层）没有 reconfigure —— 原样放过。
        # 本函数只是给输出加一层降级，不是输出本身的必经之路，
        # 装不上就退回到安装前的行为，不会因此丢掉任何数据。
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors=HANDLER_NAME)
