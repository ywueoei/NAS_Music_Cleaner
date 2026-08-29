#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
------------------------------------
# @Time    : 2026/8/29 17:07
# @Author  : Yueoei
# @File    : nas_music_cleaner.py.py
------------------------------------
"""

from __future__ import annotations
import argparse
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

"""
NAS Music Cleaner v1.1

处理流程：

第一阶段：
    只清洗文件名
    不删除文件

第二阶段：
    重新扫描
    根据清洗后的「歌手 - 歌名」进行去重

安全原则：
    默认预览
    --clean       执行第一阶段
    --dedupe      执行第二阶段
    --execute     第一阶段 + 第二阶段
"""

# ============================================================
# 音频格式
# ============================================================

LOSSLESS_EXTS = {
    ".flac",
    ".ape",
    ".wav",
    ".alac",
    ".dsf",
    ".dff",
}

LOSSY_EXTS = {
    ".mp3",
    ".aac",
    ".ogg",
    ".m4a",
    ".opus",
    ".wma",
}

ALL_EXTS = LOSSLESS_EXTS | LOSSY_EXTS


# ============================================================
# 文件名前缀编号
#
# 01. 歌名
# 01- 歌名
# 01_ 歌名
# 026_ 歌名
# 001 歌名
# ============================================================

NUMBER_PREFIX_RE = re.compile(
    r"^[\s._-]*\d{1,4}[\s._-]+"
)


# ============================================================
# 文件名杂质
# ============================================================

NOISE_PATTERNS = [

    # --------------------------------------------------------
    # 码率
    # --------------------------------------------------------

    r"[\s_\-]*(320\s*k|256\s*k|192\s*k|160\s*k|128\s*k|96\s*k|64\s*k)[\s_\-]*",

    # --------------------------------------------------------
    # 音质
    # --------------------------------------------------------

    r"[\s_\-]*(flac|ape|wav|alac|dsf|dff)[\s_\-]*",
    r"[\s_\-]*(无损|高清|高品质|高音质|超清|母带|发烧|hq|sq|bq)[\s_\-]*",

    # --------------------------------------------------------
    # 版本
    # --------------------------------------------------------

    r"[\s_\-]*(dj版|dj|remix|live|现场版|翻唱|原唱|车载|铃声|伴奏|纯音乐|instrumental)[\s_\-]*",

    # --------------------------------------------------------
    # 语言
    # --------------------------------------------------------

    r"[\s_\-]*(国语|粤语|普通话|英语|英文|eng|english|chinese)[\s_\-]*",

    # --------------------------------------------------------
    # 圆括号
    #
    # xxx (Live)
    # xxx (高清)
    # --------------------------------------------------------

    r"\([^)]*\)",

    # --------------------------------------------------------
    # 半角方括号
    #
    # xxx [mqms2]
    # xxx [高清]
    # xxx [320k]
    # --------------------------------------------------------

    r"\[[^\]]*\]",

    # --------------------------------------------------------
    # 中文方括号
    #
    # xxx 【mqms2】
    # --------------------------------------------------------

    r"【[^】]*】",

    # --------------------------------------------------------
    # 特殊书名号 / 花括号
    # --------------------------------------------------------

    r"\{[^}]*\}",
]


# ============================================================
# 格式优先级
# ============================================================

FORMAT_PRIORITY = {
    ".flac": 100,
    ".ape": 95,
    ".wav": 90,
    ".alac": 90,
    ".dsf": 90,
    ".dff": 90,

    ".mp3": 50,
    ".m4a": 48,
    ".aac": 45,
    ".ogg": 40,
    ".opus": 40,
    ".wma": 35,
}


# ============================================================
# 数据结构
# ============================================================

@dataclass
class MusicFile:

    path: Path

    original_name: str

    cleaned_name: str

    key: str

    ext: str

    bitrate: int = 0

    @property
    def is_lossless(self):
        return self.ext in LOSSLESS_EXTS

    @property
    def quality_score(self):

        try:
            size = self.path.stat().st_size
        except OSError:
            size = 0

        return (
            1 if self.is_lossless else 0,
            FORMAT_PRIORITY.get(self.ext, 0),
            self.bitrate,
            size,
        )


# ============================================================
# 文件名清洗
# ============================================================

def remove_number_prefix(name: str) -> str:

    while True:

        new_name = NUMBER_PREFIX_RE.sub("", name)

        if new_name == name:
            break

        name = new_name

    return name.strip()


def clean_filename(name: str) -> str:

    # --------------------------------------------------------
    # 1. 去序号
    # --------------------------------------------------------

    name = remove_number_prefix(name)

    # --------------------------------------------------------
    # 2. Unicode 空格
    # --------------------------------------------------------

    name = name.replace("\u3000", " ")

    # --------------------------------------------------------
    # 3. 删除杂质
    #
    # 注意：
    # 方括号 / 圆括号是整个内容删除
    # 所以：
    #
    # 陈奕迅 - 愚人快乐 [mqms2]
    #
    # 变成：
    #
    # 陈奕迅 - 愚人快乐
    # --------------------------------------------------------

    for pattern in NOISE_PATTERNS:

        name = re.sub(
            pattern,
            " ",
            name,
            flags=re.IGNORECASE,
        )

    # --------------------------------------------------------
    # 4. 清理连续空格
    # --------------------------------------------------------

    name = re.sub(
        r"\s+",
        " ",
        name,
    )

    # --------------------------------------------------------
    # 5. 统一连接符
    #
    # 陈奕迅-愚人快乐
    # 陈奕迅 -愚人快乐
    # 陈奕迅- 愚人快乐
    #
    # ↓
    #
    # 陈奕迅 - 愚人快乐
    # --------------------------------------------------------

    name = re.sub(
        r"\s*[-－—–]\s*",
        " - ",
        name,
    )

    # --------------------------------------------------------
    # 6. 清理首尾符号
    # --------------------------------------------------------

    name = name.strip()

    name = name.strip(
        " ._-－—–"
    )

    # --------------------------------------------------------
    # 7. 再清理一次空格
    # --------------------------------------------------------

    name = re.sub(
        r"\s+",
        " ",
        name,
    )

    return name.strip()


# ============================================================
# 查重 KEY
# ============================================================

def normalize_key(name: str) -> str:

    name = clean_filename(name)

    name = name.lower()

    # 去除空白
    name = re.sub(
        r"\s+",
        "",
        name,
    )

    # 统一各种连接符
    name = name.replace(
        "－",
        "-"
    )

    name = name.replace(
        "—",
        "-"
    )

    name = name.replace(
        "–",
        "-"
    )

    return name


# ============================================================
# 读取码率
# ============================================================

def get_bitrate(path: Path) -> int:

    try:

        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=bit_rate",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )

        value = result.stdout.strip()

        if value.isdigit():

            return int(value) // 1000

    except Exception:
        pass

    # 如果 ffprobe 不存在
    # 尝试从文件名获取

    match = re.search(
        r"(320|256|192|160|128|96|64)\s*k",
        path.stem,
        flags=re.IGNORECASE,
    )

    if match:

        return int(
            match.group(1)
        )

    return 0


# ============================================================
# 扫描音乐
# ============================================================

def scan_music(root: Path):

    files = []

    for path in root.rglob("*"):

        if not path.is_file():
            continue

        ext = path.suffix.lower()

        if ext not in ALL_EXTS:
            continue

        original_stem = path.stem

        cleaned = clean_filename(
            original_stem
        )

        key = normalize_key(
            original_stem
        )

        bitrate = 0

        if ext in LOSSY_EXTS:

            bitrate = get_bitrate(
                path
            )

        files.append(
            MusicFile(
                path=path,
                original_name=path.name,
                cleaned_name=cleaned,
                key=key,
                ext=ext,
                bitrate=bitrate,
            )
        )

    return files


# ============================================================
# 第一阶段：预览文件名清洗
# ============================================================

def preview_clean(files):

    candidates = []

    for music in files:

        new_name = (
            music.cleaned_name
            + music.ext
        )

        if new_name != music.original_name:

            candidates.append(
                music
            )

    print()
    print("=" * 70)
    print(
        f"【第一阶段：文件名清洗】"
        f"发现 {len(candidates)} 个文件"
    )
    print("=" * 70)

    if not candidates:

        print("没有需要清洗的文件")
        return

    for music in candidates:

        new_name = (
            music.cleaned_name
            + music.ext
        )

        print()
        print(
            f"原：{music.original_name}"
        )

        print(
            f"新：{new_name}"
        )


# ============================================================
# 执行第一阶段
# ============================================================

def execute_clean(files):

    candidates = []

    for music in files:

        new_name = (
            music.cleaned_name
            + music.ext
        )

        if new_name != music.original_name:

            candidates.append(
                music
            )

    if not candidates:

        print(
            "没有需要清洗的文件"
        )

        return

    print()
    print("=" * 70)
    print("开始执行文件名清洗")
    print("=" * 70)

    success = 0
    failed = 0

    for music in candidates:

        old_path = music.path

        new_path = (
            old_path.parent
            / (
                music.cleaned_name
                + music.ext
            )
        )

        # 目标文件已经存在
        if new_path.exists():

            print()
            print(
                "⚠️ 跳过：目标文件已存在"
            )

            print(
                f"原：{old_path}"
            )

            print(
                f"目标：{new_path}"
            )

            failed += 1

            continue

        try:

            old_path.rename(
                new_path
            )

            print(
                f"改：{old_path.name}"
                f" → "
                f"{new_path.name}"
            )

            success += 1

        except Exception as e:

            print(
                f"❌ 失败：{old_path}"
            )

            print(
                f"   {e}"
            )

            failed += 1

    print()

    print(
        f"清洗完成："
        f"成功 {success}，"
        f"失败 {failed}"
    )


# ============================================================
# 第二阶段：查重
# ============================================================

def find_duplicates(files):

    groups = defaultdict(list)

    for music in files:

        groups[
            music.key
        ].append(music)

    return {
        key: group
        for key, group in groups.items()
        if len(group) > 1
    }


# ============================================================
# 选择最佳文件
# ============================================================

def choose_keep(group):

    return max(
        group,
        key=lambda x: x.quality_score,
    )


# ============================================================
# 预览重复
# ============================================================

def preview_duplicates(
    duplicates
):

    print()
    print("=" * 70)

    print(
        f"【第二阶段：重复歌曲】"
        f"发现 {len(duplicates)} 组"
    )

    print("=" * 70)

    if not duplicates:

        print(
            "没有发现重复歌曲"
        )

        return

    total_delete = 0

    for key, group in sorted(
        duplicates.items()
    ):

        keep = choose_keep(
            group
        )

        print()
        print(
            f"歌曲：{keep.cleaned_name}"
        )

        print(
            "-" * 60
        )

        for music in sorted(
            group,
            key=lambda x:
                x.quality_score,
            reverse=True,
        ):

            if music is keep:

                marker = "【保留】"

            else:

                marker = "【删除】"

                total_delete += 1

            if music.is_lossless:

                quality = "无损"

            else:

                quality = (
                    f"{music.bitrate or '?'}K"
                )

            print(
                f"{marker} "
                f"{quality:<8} "
                f"{music.ext:<6} "
                f"{music.path}"
            )

    print()
    print(
        "-" * 70
    )

    print(
        f"预计删除："
        f"{total_delete} 个文件"
    )


# ============================================================
# 执行删除
# ============================================================

def execute_delete(
    duplicates
):

    if not duplicates:

        print(
            "没有重复文件需要删除"
        )

        return

    print()
    print("=" * 70)
    print("开始删除重复文件")
    print("=" * 70)

    deleted = 0
    failed = 0

    for key, group in duplicates.items():

        keep = choose_keep(
            group
        )

        for music in group:

            if music is keep:
                continue

            try:

                music.path.unlink()

                print(
                    f"删：{music.path}"
                )

                deleted += 1

            except Exception as e:

                print(
                    f"❌ 删除失败："
                    f"{music.path}"
                )

                print(
                    f"   {e}"
                )

                failed += 1

    print()

    print(
        f"删除完成："
        f"成功 {deleted}，"
        f"失败 {failed}"
    )


# ============================================================
# 主程序
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=
        "NAS Music Cleaner v1.1"
    )

    parser.add_argument(
        "path",
        nargs="?",
        default=
        "/vol1/1000/music",
        help=
        "音乐库目录",
    )

    parser.add_argument(
        "--clean",
        action="store_true",
        help=
        "执行第一阶段：清洗文件名",
    )

    parser.add_argument(
        "--dedupe",
        action="store_true",
        help=
        "执行第二阶段：删除重复歌曲",
    )

    parser.add_argument(
        "--execute",
        action="store_true",
        help=
        "执行清洗 + 去重",
    )

    args = parser.parse_args()

    root = Path(
        args.path
    ).expanduser().resolve()

    if not root.exists():

        print(
            f"❌ 目录不存在：{root}"
        )

        sys.exit(1)

    if not root.is_dir():

        print(
            f"❌ 不是目录：{root}"
        )

        sys.exit(1)

    print()
    print(
        "╔══════════════════════════════════════════════════════════════════╗"
    )

    print(
        "║                  🎵 NAS Music Cleaner v1.1                    ║"
    )

    print(
        "║                                                                  ║"
    )

    print(
        "║  第一阶段：清洗文件名，不删除文件                               ║"
    )

    print(
        "║  第二阶段：重新扫描后进行智能去重                               ║"
    )

    print(
        "║                                                                  ║"
    )

    print(
        "║  无损优先 → 最高码率 → 文件大小                                  ║"
    )

    print(
        "╚══════════════════════════════════════════════════════════════════╝"
    )

    print()

    print(
        f"音乐库：{root}"
    )

    # ========================================================
    # 第一次扫描
    # ========================================================

    files = scan_music(
        root
    )

    print(
        f"发现 {len(files)} 个音频文件"
    )

    # ========================================================
    # 默认：只预览
    # ========================================================

    if not (
        args.clean
        or args.dedupe
        or args.execute
    ):

        # 第一阶段预览
        preview_clean(
            files
        )

        # 第二阶段预览
        #
        # 注意：
        # 这里暂时按照当前文件名预览
        # 真正执行 --execute 时会先清洗，
        # 然后重新扫描。
        #

        duplicates = find_duplicates(
            files
        )

        preview_duplicates(
            duplicates
        )

        print()
        print("=" * 70)
        print("当前为【预览模式】")
        print("=" * 70)

        print()
        print(
            "第一阶段："
        )

        print(
            f"  python3 {Path(sys.argv[0]).name} "
            f"\"{root}\" --clean"
        )

        print()
        print(
            "第二阶段："
        )

        print(
            f"  python3 {Path(sys.argv[0]).name} "
            f"\"{root}\" --dedupe"
        )

        print()
        print(
            "全部执行："
        )

        print(
            f"  python3 {Path(sys.argv[0]).name} "
            f"\"{root}\" --execute"
        )

        print()

        return

    # ========================================================
    # --clean
    # ========================================================

    if args.clean:

        print()
        print(
            "⚠️ 即将执行第一阶段："
        )

        print(
            "   只清洗文件名"
        )

        print(
            "   不删除任何文件"
        )

        print()

        confirm = input(
            "请输入 CLEAN 确认："
        )

        if confirm == "CLEAN":

            execute_clean(
                files
            )

        else:

            print(
                "已取消"
            )

    # ========================================================
    # --dedupe
    # ========================================================

    if args.dedupe:

        # ----------------------------------------------------
        # 第二阶段必须重新扫描
        # ----------------------------------------------------

        print()
        print(
            "重新扫描清洗后的音乐库……"
        )

        files = scan_music(
            root
        )

        duplicates = find_duplicates(
            files
        )

        preview_duplicates(
            duplicates
        )

        print()

        confirm = input(
            "⚠️ 请输入 DELETE 确认删除："
        )

        if confirm == "DELETE":

            execute_delete(
                duplicates
            )

        else:

            print(
                "已取消"
            )

    # ========================================================
    # --execute
    # ========================================================

    if args.execute:

        print()
        print("=" * 70)

        print(
            "⚠️ 即将执行完整流程"
        )

        print("=" * 70)

        print()
        print(
            "第一步：清洗文件名"
        )

        print(
            "第二步：重新扫描"
        )

        print(
            "第三步：智能去重"
        )

        print()
        print(
            "删除规则："
        )

        print(
            "  无损 > 有损"
        )

        print(
            "  格式优先级"
        )

        print(
            "  最高码率"
        )

        print(
            "  文件大小"
        )

        print()

        confirm = input(
            "请输入 YES 确认执行："
        )

        if confirm != "YES":

            print(
                "已取消"
            )

            return

        # ----------------------------------------------------
        # 第一阶段
        # ----------------------------------------------------

        execute_clean(
            files
        )

        # ----------------------------------------------------
        # 第二阶段
        #
        # 关键：
        # 必须重新扫描
        # ----------------------------------------------------

        print()
        print(
            "重新扫描清洗后的音乐库……"
        )

        files = scan_music(
            root
        )

        duplicates = find_duplicates(
            files
        )

        # ----------------------------------------------------
        # 显示最终删除清单
        # ----------------------------------------------------

        preview_duplicates(
            duplicates
        )

        print()

        confirm = input(
            "请输入 DELETE 确认删除重复文件："
        )

        if confirm != "DELETE":

            print(
                "已取消删除"
            )

            return

        # ----------------------------------------------------
        # 删除
        # ----------------------------------------------------

        execute_delete(
            duplicates
        )

        print()
        print("=" * 70)
        print(
            "🎵 NAS Music Cleaner 完成"
        )
        print("=" * 70)


if __name__ == "__main__":
    main()
