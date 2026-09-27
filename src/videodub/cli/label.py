"""label 子命令 — 查看/校正说话人标注与断句（自动分离易错，人工兜底）

典型三步（见根 README）：
  videodub transcribe input.mp4 --diarize                          # → output/<名>/01_transcript.json
  videodub label output/<名>/01_transcript.json --media input.mp4  # → 同目录 02_labeled.json
  videodub run input.mp4 --segments-json 02_labeled.json ...       # → output/<名>/03_成品.mp4

交互为逐句审阅流（rich 排版，不整表刷屏）：启动显示说话人分组概览 + 当前句附近的窗口，
光标句高亮，Enter 跳下一句，直接按 0/1/2 给当前句改说话人并续走：
  0/1/2            当前句改为对应说话人并前进
  13=0             任意句改人（支持 13,17=0 批量 · 10-18=0 区间）
  m 1-3 [文本]     合并碎句，如 m 3,4 · m 3-5 我们这里是药店，买酒到隔壁。可顺带修标点
  x 4 A|B          拆句，如 x 4 我们这里是|药店；可指定秒数 x 4 5.0 A|B
  d 13             删除噪声/幻觉句（支持批量/区间）
  p 13             试听原视频对应片段（需 --media）
  l [编号]         定位跳转 / 重看概览
  r                从头开始审阅（末尾 Enter 后有提示）
  u                撤销上一次操作（结构与说话人均可撤）
  w 保存退出 · q 放弃退出；? / ？ 展开完整帮助

错别字修正直接编辑 02_labeled.json 的 text 字段（面板不改台词正文）。
脚本化替代：--apply 回填文件（稀疏合并，未填写的保留原标注）。
人数不限：编号 0/1/2… 归一化为 SPEAKER_0/SPEAKER_1/...
"""

import collections
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from videodub.domain.transcript import normalize_speaker
from videodub.utils.logger import log_error, log_success, log_warning


def build_parser(parser) -> None:
    parser.add_argument("input", help="台词 JSON（01_transcript.json）")
    parser.add_argument("-o", "--output", default=None,
                        help="输出路径（默认：输入为 01_* 时 → 同目录 02_labeled.json，否则 <输入名>_labeled.json）")
    parser.add_argument("--media", default=None, help="原视频/音频路径（提供后可用 p 命令试听句子）")
    parser.add_argument("--apply", default=None, metavar="FILE", help="跳过交互，从 JSON 回填说话人（稀疏合并）")

    parser.set_defaults(func=_run)


# ── 文件读写 ──

def _load_json_list(path: str) -> list[dict]:
    """读取 JSON 数组（供回填文件使用，只要求是对象列表）"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
        raise ValueError(f"{path} 不是 JSON 对象列表")
    return data


def _load_items(path: str) -> list[dict]:
    """读取并校验台词 JSON（列表，每项含 start/end/text）"""
    data = _load_json_list(path)
    if any("start" not in item or "end" not in item or "text" not in item for item in data):
        raise ValueError(f"{path} 不是合法的台词 JSON（应为包含 start/end/text 的列表）")
    return data


def _clean_speaker(value, *, index: int, seg_id: str) -> str:
    """把用户填的说话人统一为 SPEAKER_N（int / 数字字符串 / SPEAKER_N 均可）"""
    if isinstance(value, int):
        return normalize_speaker(value)
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith("SPEAKER_"):
            num = raw[len("SPEAKER_"):]
            if num.isdigit():
                return f"SPEAKER_{int(num)}"
        elif raw.isdigit():
            return f"SPEAKER_{int(raw)}"
    raise ValueError(f"第 {index} 句（{seg_id}）的 speaker 无法解析: {value!r}（请填 0/1/2… 或 SPEAKER_0）")


def _run_apply(base_items: list[dict], apply_path: str) -> list[dict]:
    """回填模式：按位置合并说话人，未填写的保留原始标注（适合稀疏校错）"""
    edited = _load_json_list(apply_path)
    if len(edited) != len(base_items):
        raise ValueError(
            f"回填文件 {apply_path} 的台词数 {len(edited)} 与原始 {len(base_items)} 不一致"
        )
    labeled: list[dict] = []
    unlabeled: list[str] = []
    for index, (base, note) in enumerate(zip(base_items, edited), start=1):
        seg_id = base.get("id") or f"seg_{index:04d}"
        segment = dict(base)
        speaker = note.get("speaker")
        if speaker is not None:
            segment["speaker"] = _clean_speaker(speaker, index=index, seg_id=seg_id)
        if segment.get("speaker") is None:
            unlabeled.append(seg_id)
        labeled.append(segment)
    if unlabeled:
        log_warning(f"以下 {len(unlabeled)} 句仍未标注: {', '.join(unlabeled)}")
    return labeled


def _write(output_path: Path, items: list[dict]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _summarize(items: list[dict]) -> None:
    counts = collections.Counter(seg.get("speaker") for seg in items if seg.get("speaker"))
    if not counts:
        log_warning("没有任何说话人标注被写入")
        return
    detail = ", ".join(f"{spk}: {n} 句" for spk, n in sorted(counts.items()))
    log_success(f"标注完成: 共 {len(items)} 句，{len(counts)} 个说话人（{detail}）")


# ── 面板显示（rich 排版）──

_SPK_COLORS = {
    "0": "cyan",
    "1": "magenta",
    "2": "green",
    "3": "yellow",
    "4": "bright_white",
    "5": "red",
}
_UNKNOWN_COLOR = "grey50"
_WINDOW_HALF = 3        # 光标上下各看 3 句，避免整表刷屏
_BODY_WIDTH = 48        # 台词显示宽度（中文按 2 宽截断）
_console = Console(soft_wrap=True)


def _short(speaker) -> str:
    """SPEAKER_3 → '3'；None → '?'（面板短显示）"""
    return "?" if speaker is None else str(speaker).removeprefix("SPEAKER_")


def _spk_color(key: str) -> str:
    """说话人短编号 → 颜色；'?' 用灰色"""
    if key == "?":
        return _UNKNOWN_COLOR
    try:
        return _SPK_COLORS.get(str(int(key)), "bright_white")
    except (ValueError, TypeError):
        return "bright_white"


def _spk_tag(key: str) -> Text:
    """『人3』/『?』样式的说话人徽标（带颜色）"""
    tag = "?" if key == "?" else f"人{key}"
    return Text(tag, style=f"bold {_spk_color(key)}")


def _status_bar(items: list[dict]) -> Text:
    """底部统计条：说话人分布 + 未标注数"""
    counts: dict[str, int] = collections.Counter(_short(seg.get("speaker")) for seg in items)
    parts: list[Text] = []
    for key in ("0", "1", "2", "3", "4", "5", "?"):
        if key in counts:
            label = f"未标×{counts[key]}" if key == "?" else f"人{key}×{counts[key]}"
            parts.append(Text(label, style=f"bold {_spk_color(key)}"))
    return Text("    ").join(parts)


def _truncate(text: str, width: int) -> str:
    """按显示宽度截断台词，尾部加 …"""
    if not text:
        return ""
    out, w = [], 0
    for ch in text:
        cw = 2 if ord(ch) > 0x2E7F else 1
        if w + cw > width:
            out.append("…")
            break
        out.append(ch)
        w += cw
    return "".join(out)


def _segment_line(seg: dict, index: int, *, cursor: int | None = None) -> Text:
    """单句渲染行：编号 时间 说话人 台词（光标句才标 ▶ 并加粗）"""
    key = _short(seg.get("speaker"))
    t0, t1 = float(seg["start"]), float(seg["end"])
    line = Text(f"{'▶' if index == cursor else ' '} {index:03d}  ")
    line.append(f"{t0:6.1f}-{t1:6.1f}s  ", style="grey53")
    line.append(_spk_tag(key))
    line.append("  ")
    body = _truncate(str(seg["text"]), _BODY_WIDTH)
    line.append(body, style="bold" if index == cursor else "white")
    return line


def _print_overview(items: list[dict]) -> None:
    """按说话人分组的编号概览（rich Panel，彩色编号）"""
    groups: dict[str, list[int]] = collections.defaultdict(list)
    for index, segment in enumerate(items, start=1):
        groups[_short(segment.get("speaker"))].append(index)
    order = sorted(groups, key=lambda k: (k == "?", int(k) if k != "?" else 0))
    lines: list[Text] = []
    for key in order:
        tag = _spk_tag(key)
        nums = Text(" | ".join(
            " ".join(f"{n:02d}" for n in groups[key][i:i + 15])
            for i in range(0, len(groups[key]), 15)
        ), style=_spk_color(key))
        lines.append(Text("  ").join([tag, Text("  "), nums]))
    panel = Panel(
        Text("\n\n").join(lines) if lines else Text("（无句子）"),
        title="[bold]说话人分组概览[/]",
        border_style="dim",
    )
    _console.print(panel)


def _print_window(items: list[dict], cursor: int) -> None:
    """光标附近窗口：上下各 _WINDOW_HALF 句，光标句高亮（不刷屏）"""
    total = len(items)
    lo = max(1, cursor - _WINDOW_HALF)
    hi = min(total, cursor + _WINDOW_HALF)
    for index in range(lo, hi + 1):
        _console.print(_segment_line(items[index - 1], index, cursor=cursor if index == cursor else None))


def _print_focused(items: list[dict], cursor: int) -> None:
    """光标句放大视图：看清当前句全文（不截断）再编辑"""
    seg = items[cursor - 1]
    key = _short(seg.get("speaker"))
    t0, t1 = float(seg["start"]), float(seg["end"])
    line = Text("▶ ")
    line.append(f"{cursor:03d}  ", style="bold yellow")
    line.append(f"{t0:6.1f}-{t1:6.1f}s  ", style="grey53")
    line.append(_spk_tag(key))
    line.append("  ")
    line.append(str(seg["text"]), style="bold")
    panel = Panel(line, border_style="bold yellow", title="[bold yellow]当前句[/]")
    _console.print(panel)


def _parse_selector(spec: str, total: int) -> list[int]:
    """'13' / '13,17' / '10-18' / '3,8,10-12' → 1-based 编号列表（去重升序）"""
    picked: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, _, hi = part.partition("-")
            lo, hi = lo.strip(), hi.strip()
            if not (lo.isdigit() and hi.isdigit()):
                raise ValueError(f"无法解析编号: {part}")
            a, b = int(lo), int(hi)
            if a > b:
                a, b = b, a
            picked.update(range(a, b + 1))
        elif part.isdigit():
            picked.add(int(part))
        else:
            raise ValueError(f"无法解析编号: {part}")
    bad = sorted(n for n in picked if not 1 <= n <= total)
    if bad:
        shown = "、".join(str(n) for n in bad)
        raise ValueError(f"编号越界: {shown}（共 {total} 句）")
    return sorted(picked)


def _is_number(text: str) -> bool:
    """能否解析为浮点数（x 命令里区分切分秒数与正文）"""
    try:
        float(text)
    except ValueError:
        return False
    return True


def _snapshot(items: list[dict]) -> list[dict]:
    """修改前的完整快照（每句浅拷贝），供撤销"""
    return [dict(seg) for seg in items]


def _renumber_ids(items: list[dict]) -> None:
    """结构改动（拆/并/删）后重排 id，保持 id 与位置一致（下游按 id 关联配音计划）"""
    for index, seg in enumerate(items, start=1):
        seg["id"] = f"seg_{index:04d}"


def _merge_segments(items: list[dict], numbers: list[int], text: str | None = None) -> None:
    """把连续编号的句子合并为一句：时间取并集、说话人取第一个非空。

    text 缺省时按原样拼接各句文本；给出时直接采用（合并顺带修标点）。
    校验失败抛 ValueError 且不修改 items。
    """
    if len(numbers) < 2:
        raise ValueError("至少选择两句才能合并")
    if numbers != list(range(numbers[0], numbers[-1] + 1)):
        raise ValueError("只能合并连续编号，如 m 3,4 或 m 3-5")
    segs = [items[n - 1] for n in numbers]
    merged = dict(segs[0])
    merged["start"] = min(float(s["start"]) for s in segs)
    merged["end"] = max(float(s["end"]) for s in segs)
    merged["text"] = text if text else "".join(str(s["text"]) for s in segs)
    speaker = next((s["speaker"] for s in segs if s.get("speaker") is not None), None)
    if speaker is None:
        merged.pop("speaker", None)
    else:
        merged["speaker"] = speaker
    items[numbers[0] - 1:numbers[-1]] = [merged]
    _renumber_ids(items)


def _split_segment(items: list[dict], number: int, text_a: str, text_b: str,
                   at_time: float | None) -> float:
    """把第 number 句拆成两句（两半继承原说话人），返回切分点秒数。

    at_time 缺省时按两段文本字数比例估算。校验失败抛 ValueError 且不修改 items。
    """
    seg = items[number - 1]
    start, end = float(seg["start"]), float(seg["end"])
    if at_time is None:
        at_time = start + (end - start) * len(text_a) / (len(text_a) + len(text_b))
    if not start < at_time < end:
        raise ValueError(f"切分点 {at_time:g}s 不在第 {number} 句范围 {start:g}-{end:g}s 内")
    at_time = round(at_time, 3)
    first = dict(seg)
    first["end"] = at_time
    first["text"] = text_a
    second = dict(seg)
    second["start"] = at_time
    second["text"] = text_b
    items[number - 1:number] = [first, second]
    _renumber_ids(items)
    return at_time


def _delete_segments(items: list[dict], numbers: list[int]) -> None:
    """删除选中句子（识别幻觉/噪声段）"""
    for n in sorted(numbers, reverse=True):
        del items[n - 1]
    _renumber_ids(items)


def _apply_edit(items: list[dict], numbers: list[int], spk: int) -> bool:
    """把选中句子改为 SPEAKER_<spk>；返回是否发生改动"""
    target = f"SPEAKER_{spk}"
    batch = [n for n in numbers if items[n - 1].get("speaker") != target]
    if not batch:
        _console.print(f"  ← 第 {'、'.join(map(str, numbers))} 句已全是 {target}，未改动", style="yellow")
        return False
    for n in batch:
        items[n - 1]["speaker"] = target
    _console.print(f"  ✓ {len(batch)} 句 → {target}", style="green")
    return True


def _play(media: str, items: list[dict], numbers: list[int]) -> None:
    """用 ffplay 逐句播放原媒体对应片段（听完自动返回提示符）"""
    ffplay = shutil.which("ffplay")
    if not ffplay:
        _console.print("  ← 未找到 ffplay，无法播放", style="yellow")
        return
    for n in numbers:
        segment = items[n - 1]
        duration = max(float(segment["end"]) - float(segment["start"]), 0.1)
        _console.print(f"  试听 {n:4d}  {segment['text']}", style="cyan")
        subprocess.run(
            [ffplay, "-autoexit", "-loglevel", "quiet",
             "-ss", str(segment["start"]), "-t", f"{duration:.2f}", media],
            check=False,
        )


_HINT = "Enter 下一句 · 0/1/2 改当前句并前进 · ? / ？ 帮助 · w 保存 · q 放弃"


def _print_help(console: Console) -> None:
    """命令帮助：先讲清楚概念，再按用途分组排版"""
    intro = Text.assemble(
        "命令帮助 · ",
        ("▶ 当前句", "bold yellow"), " = 光标所在句（高亮）。说话人 0/1/2 是自动分人得到的角色编号。",
    )

    def group(title: str, rows) -> Panel:
        table = Table(box=None, show_header=False, pad_edge=False, expand=False)
        table.add_column(style="bold cyan", no_wrap=True)
        table.add_column(overflow="fold")
        for cmd, desc in rows:
            table.add_row(cmd, desc)
        return Panel(table, title=f"[bold]{title}[/]", border_style="dim",
                     padding=(0, 1))

    spk = group("分人（视频里有几个人，就标几）", [
        ("0 / 1 / 2", "当前句分给说话人 0/1/2，并跳到下一句（最常用）"),
        ("13=0", "指定句改人：13=0 · 13,17=0 批量 · 10-18=1 区间"),
    ])
    seg = group("断句（识别已预切，碎/长再调）", [
        ("m 3,4", "合并碎句；m 3-5 文本 可带合并后全文修标点"),
        ("x 3 A|B", "一句拆两句；x 3 5.5 A|B 可指定切分秒数"),
        ("d 13", "删除噪声/幻觉句（支持批量/区间）"),
    ])
    misc = group("复查与收尾", [
        ("15", "直接输入编号/区间/列表 = 跳到该句，如 15 · 10-18 · 3,8"),
        ("l [编号]", "同定位；无编号重看分组概览"),
        ("p 13", "试听原视频对应片段（需 --media）"),
        ("r", "回到第 1 句重头审阅"),
        ("u", "撤销上一步"),
        ("? / ？", "本帮助 · w 保存退出 · q 放弃退出"),
    ])
    console.print(intro)
    console.print(spk)
    console.print(seg)
    console.print(misc)


def _run_repl(items: list[dict], media: str | None, output_path: Path) -> bool:
    """逐句审阅流。返回 True = 保存，False = 放弃"""
    global _console
    for stream in (sys.stdout, sys.stdin):
        try:
            stream.reconfigure(encoding="utf-8")  # Windows 控制台防中文乱码
        except (AttributeError, ValueError, OSError):
            pass
    _console = Console(soft_wrap=True)

    total = len(items)
    cursor = min(1, total)  # 当前审阅到第几句（1-based）

    def refresh(show_overview: bool = False) -> None:
        _console.print()
        if show_overview:
            _print_overview(items)
            _console.print()
        # 常驻状态条：说话人分布 + 审阅进度 + 调出总览提示，每次刷新都可见
        bar = Text.assemble(
            (f"第 {cursor}/{len(items)} 句  ", "bold"),
            _status_bar(items),
            Text("   l 调出总览", style="dim"),
        )
        _console.print(bar)
        _print_window(items, cursor)
        _print_focused(items, cursor)
        _console.print(_HINT, style="dim")

    undo_stack: list[tuple[list[dict], int]] = []  # (修改前快照, 修改前光标)

    def commit(snapshot: list[dict], old_cursor: int) -> None:
        undo_stack.append((snapshot, old_cursor))

    refresh(show_overview=True)

    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            _console.print()
            if undo_stack:
                log_warning("有未保存的修改，已放弃")
            return False
        if not line:
            # 回车 = 跳到下一句（最常见的逐句过审操作）；已到末尾则提示下一步
            if cursor < len(items):
                cursor += 1
                refresh()
            else:
                _console.print("  已到末尾：r 从头审阅 · w 保存退出", style="dim")
            continue

        cmd = line.lower()

        if cmd in ("w", "wq"):
            return True
        if cmd == "q":
            if undo_stack:
                confirm = input("  有未保存修改，确认放弃? (y/N): ").strip().lower()
                if confirm != "y":
                    continue
            _console.print("  已放弃，未写入文件")
            return False
        if cmd in ("?", "？", "help"):
            _print_help(_console)
            refresh()
            continue
        if cmd == "r":
            if cursor == 1:
                _console.print("  已在第 1 句", style="dim")
                continue
            cursor = 1
            _console.print("  ✓ 已回到第 1 句", style="green")
            refresh()
            continue
        if cmd == "u":
            if not undo_stack:
                _console.print("  ← 没有可撤销的操作", style="yellow")
                continue
            items[:], cursor = undo_stack.pop()
            cursor = min(cursor, len(items))
            _console.print("  ✓ 已撤销上一次操作", style="green")
            refresh()
            continue

        if cmd == "m" or cmd.startswith("m "):
            arg = line[1:].strip()
            if not arg:
                _console.print("  ← 用法: m <编号> [合并后文本]（编号间不加空格），如 m 3,4 · m 3-5 我们这里是药店，买酒到隔壁。", style="yellow")
                continue
            # 第一个空白分隔的 token 是编号选择器，其余是可选的合并后完整文本
            head, _, tail = arg.partition(" ")
            selector, custom_text = head, tail.strip() or None
            try:
                numbers = _parse_selector(selector, len(items))
            except ValueError as exc:
                _console.print(f"  ← {exc}", style="yellow")
                continue
            snapshot, old_cursor = _snapshot(items), cursor
            try:
                _merge_segments(items, numbers, custom_text)
            except ValueError as exc:
                _console.print(f"  ← {exc}", style="yellow")
                continue
            commit(snapshot, old_cursor)
            cursor = min(numbers[0], len(items))
            _console.print(f"  ✓ 已合并 {len(numbers)} 句 → 第 {cursor} 句", style="green")
            refresh()
            continue

        if cmd == "x" or cmd.startswith("x "):
            usage = ("  ← 用法: x <编号> <文本A>|<文本B>，如 x 3 我们这里是药店|买酒到隔壁\n"
                     "        指定切分秒数: x <编号> <秒> <文本A>|<文本B>")
            parts = line[1:].strip().split(None, 1)
            if len(parts) < 2 or not parts[0].isdigit():
                _console.print(usage, style="yellow")
                continue
            number = int(parts[0])
            if not 1 <= number <= len(items):
                _console.print(f"  ← 编号越界: {number}（共 {len(items)} 句）", style="yellow")
                continue
            tail = parts[1].strip()
            at_time = None
            head = tail.split(None, 1)
            if head and _is_number(head[0]):
                at_time = float(head[0])
                tail = head[1].strip() if len(head) > 1 else ""
            if "|" not in tail:
                _console.print(usage, style="yellow")
                continue
            text_a, _, text_b = tail.partition("|")
            text_a, text_b = text_a.strip(), text_b.strip()
            if not text_a or not text_b:
                _console.print("  ← 两段文本都不能为空", style="yellow")
                continue
            snapshot, old_cursor = _snapshot(items), cursor
            try:
                at = _split_segment(items, number, text_a, text_b, at_time)
            except ValueError as exc:
                _console.print(f"  ← {exc}", style="yellow")
                continue
            commit(snapshot, old_cursor)
            cursor = min(number, len(items))
            _console.print(f"  ✓ 第 {number} 句已拆为两句（切分点 {at:g}s）", style="green")
            refresh()
            continue

        if cmd == "d" or cmd.startswith("d "):
            arg = line[1:].strip()
            if not arg:
                _console.print("  ← 用法: d <编号>（删除句子），如 d 13 · d 13,17 · d 10-12", style="yellow")
                continue
            try:
                numbers = _parse_selector(arg, len(items))
            except ValueError as exc:
                _console.print(f"  ← {exc}", style="yellow")
                continue
            snapshot, old_cursor = _snapshot(items), cursor
            _delete_segments(items, numbers)
            commit(snapshot, old_cursor)
            cursor = min(min(numbers), len(items))
            _console.print(f"  ✓ 已删除 {len(numbers)} 句", style="green")
            refresh()
            continue

        if cmd == "p" or cmd.startswith("p "):
            if not media:
                _console.print("  ← 未提供 --media，无法试听（用法: videodub label <json> --media <视频>）", style="yellow")
                continue
            if not Path(media).exists():
                _console.print(f"  ← 媒体文件不存在: {media}", style="yellow")
                continue
            arg = line[1:].strip()
            if not arg:
                _console.print("  ← 用法: p <编号>，如 p 13 · p 13-15", style="yellow")
                continue
            try:
                numbers = _parse_selector(arg, len(items))
            except ValueError as exc:
                _console.print(f"  ← {exc}", style="yellow")
                continue
            _play(media, items, numbers)
            refresh()
            continue
        if cmd == "l" or cmd.startswith("l "):
            arg = line[1:].strip()
            if arg:
                try:
                    numbers = _parse_selector(arg, len(items))
                except ValueError as exc:
                    _console.print(f"  ← {exc}", style="yellow")
                    continue
                cursor = numbers[0]
                refresh()
                continue
            refresh(show_overview=True)
            continue
        if "=" in line:
            selector, _, spk = line.partition("=")
            selector, spk = selector.strip(), spk.strip()
            if not selector or not spk.isdigit():
                _console.print("  ← 语法: <编号>=<说话人>，如 13=0 · 13,17=0 · 10-18=1", style="yellow")
                continue
            try:
                numbers = _parse_selector(selector, len(items))
            except ValueError as exc:
                _console.print(f"  ← {exc}", style="yellow")
                continue
            snapshot, old_cursor = _snapshot(items), cursor
            if _apply_edit(items, numbers, int(spk)):
                commit(snapshot, old_cursor)
                if cursor in numbers:
                    cursor = min(numbers[0], len(items))
            refresh()
            continue

        # 纯数字：单数字 = 给当前句改说话人并前进（审阅流核心）；多位数 = 定位跳转
        if line.isdigit():
            if len(line) == 1 and 0 <= int(line) <= 9:
                snapshot, old_cursor = _snapshot(items), cursor
                if _apply_edit(items, [cursor], int(line)):
                    commit(snapshot, old_cursor)
                if cursor < len(items):
                    cursor += 1
                refresh()
                continue
            number = int(line)
            if 1 <= number <= len(items):
                cursor = number
                refresh()
                continue
            _console.print(f"  ← 编号越界: {number}（共 {len(items)} 句）", style="yellow")
            continue

        # 直接输区间/列表（如 10-18 · 13,17）也视为定位跳转（同 l N）
        if re.fullmatch(r"[\d,\-\s]+", line):
            try:
                numbers = _parse_selector(line, len(items))
            except ValueError as exc:
                _console.print(f"  ← {exc}", style="yellow")
                continue
            cursor = numbers[0]
            refresh()
            continue

        _console.print("  ← 无法识别该命令，输入 ? 查看帮助", style="yellow")


# ── 入口 ──

def _default_output(input_path: Path) -> Path:
    """默认输出：01_* → 同目录 02_labeled.json；已是 labeled 文件 → 就地覆盖；其他 → <名>_labeled.json"""
    if input_path.name.startswith("01_"):
        return input_path.with_name("02_labeled.json")
    if "labeled" in input_path.name:
        return input_path  # 已标注文件再编辑：原地迭代
    return input_path.with_name(f"{input_path.stem}_labeled.json")


def _run(args) -> int:
    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else _default_output(input_path)
    try:
        items = _load_items(args.input)
        if args.apply:
            labeled = _run_apply(items, args.apply)
            _write(output_path, labeled)
            _summarize(labeled)
            return 0
        if _run_repl(items, args.media, output_path):
            _write(output_path, items)
            _summarize(items)
        return 0
    except (ValueError, OSError) as exc:
        log_error(str(exc))
        return 1