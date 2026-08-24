"""audiotool 核心模块：ffmpeg 命令行拼接与调用封装。

设计原则（自包含工具，复制优于共享）：
    本模块只做两件事——
        1) build_*_cmd：纯函数，拼接 ffmpeg 命令行参数列表（不含程序名）。
        2) run_ffmpeg ：通过 subprocess 真正调用 ffmpeg 子进程。
    build_*_cmd 不依赖 ffmpeg 是否存在，可脱离运行时独立测试。

全哥踩坑经验（务必遵循，已写入实现注释）：
    * 混音 / 淡入淡出：绝对避免 `afade=t=out` —— 它会把整段压成静音(-91dB)。
      音量增益请用显式滤镜 `volume=1.5` 之类。
    * 多文件合并：用 concat demuxer（生成临时 list 文件），不要用 aloop，
      本机 aloop 失效。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import List, Optional, Tuple

# 支持的音频目标格式（转换 / 合并输出）
AUDIO_FORMATS: Tuple[str, ...] = ("mp3", "wav", "ogg", "flac")

# 各格式对应的音频编码（用于“从视频提取音频”时重新编码，保证容器兼容）
_CODEC_FOR_EXT: dict[str, str] = {
    "mp3": "libmp3lame",
    "wav": "pcm_s16le",
    "ogg": "libvorbis",
    "flac": "flac",
}

# loudnorm 默认参数（播客/语音常用目标响度）
_LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"


def ffmpeg_path() -> Optional[str]:
    """返回可用的 ffmpeg 可执行文件路径；找不到返回 ``None``。

    查找顺序：
        1. 环境变量 ``AUDIOTOOL_FFMPEG`` 指向的文件（若存在）。
        2. ``shutil.which('ffmpeg')`` 在系统 PATH 中查找。

    返回:
        ffmpeg 绝对/相对路径字符串，或 ``None``。
    """
    env_path = os.environ.get("AUDIOTOOL_FFMPEG")
    if env_path and os.path.isfile(env_path):
        return env_path
    return shutil.which("ffmpeg")


def run_ffmpeg(args: List[str], timeout: int = 300) -> Tuple[int, str, str]:
    """调用 ffmpeg 子进程。

    参数:
        args:   已拼好的命令行参数列表（**不含** ``ffmpeg`` 程序名本身，
                即 ``build_*_cmd`` 的返回值）。
        timeout: 超时秒数，默认 300。

    返回:
        ``(returncode, stdout, stderr)`` 三元组。

    异常:
        FileNotFoundError : 环境中找不到 ffmpeg。
        subprocess.TimeoutExpired : 超过 ``timeout`` 秒仍未结束。
    """
    exe = ffmpeg_path()
    if exe is None:
        raise FileNotFoundError(
            "未找到 ffmpeg：请安装并加入 PATH，或设置环境变量 "
            "AUDIOTOOL_FFMPEG 指向 ffmpeg.exe。"
        )
    cmd = [exe, *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:  # 超时后确保子进程被回收
        raise
    return proc.returncode, proc.stdout, proc.stderr


def build_convert_cmd(src: str, dst: str, fmt: str) -> List[str]:
    """构建“格式转换”命令。

    将 ``src`` 转换为目标格式 ``fmt``（mp3/wav/ogg/flac）。
    输出扩展名会被规范化为 ``fmt``。

    参数:
        src: 源音频文件路径。
        dst: 期望的输出路径（扩展名会被覆盖为 fmt）。
        fmt: 目标格式，取值见 ``AUDIO_FORMATS``。

    返回:
        ffmpeg 参数字符串列表，例如
        ``['-y', '-i', 'a.wav', 'a.mp3']``。

    异常:
        ValueError: fmt 不在支持列表中。
    """
    fmt = (fmt or "").lower()
    if fmt not in AUDIO_FORMATS:
        raise ValueError(f"不支持的目标格式: {fmt!r}，可选 {AUDIO_FORMATS}")
    base, _ = os.path.splitext(dst)
    dst = base + "." + fmt
    # -y 覆盖已存在文件；默认重新编码为对应格式
    return ["-y", "-i", src, dst]


def _to_seconds(value) -> float:
    """把 ``'mm:ss'`` / ``'hh:mm:ss'`` / 秒数(数字或字符串) 统一转换为秒(float)。

    参数:
        value: ``None`` 视为 0；数字直接转 float；含 ``:`` 的字符串按时间分段解析。

    返回:
        浮点秒数。

    异常:
        ValueError: 无法解析的输入。
    """
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return 0.0
    if ":" in s:
        try:
            parts = [float(p) for p in s.split(":")]
        except ValueError as exc:
            raise ValueError(f"时间格式无法解析: {value!r}") from exc
        secs = 0.0
        for p in parts:
            secs = secs * 60 + p
        return secs
    return float(s)


def build_trim_cmd(src: str, dst: str, start, end=None) -> List[str]:
    """构建“裁剪”命令。

    参数:
        src:   源文件。
        dst:   输出文件。
        start: 起始时间，``'mm:ss'`` 或秒数。
        end:   结束时间，``'mm:ss'`` 或秒数；``None`` 表示裁剪到结尾。

    实现说明（全哥经验）：
        使用 ``-ss``(输入定位，快速) + ``-t``(时长) 进行裁剪，
        并以 ``-c copy`` 流复制避免重新编码、保质量。
        注意：流复制方式对部分有损格式(如 mp3)非帧级精确，属已知限制。

    返回:
        ffmpeg 参数字符串列表。
    """
    start_s = _to_seconds(start)
    if start_s < 0:
        raise ValueError("start 不能为负数")
    args = ["-y", "-ss", f"{start_s:.3f}", "-i", src]
    if end is not None:
        end_s = _to_seconds(end)
        if end_s <= start_s:
            raise ValueError("end 必须大于 start")
        dur = end_s - start_s
        args += ["-t", f"{dur:.3f}"]
    args += ["-c", "copy", dst]
    return args


def build_normalize_cmd(src: str, dst: str) -> List[str]:
    """构建“音量归一”命令，使用 ``loudnorm`` 滤镜。

    参数:
        src: 源文件。
        dst: 输出文件。

    实现说明（全哥经验）：
        音量调整一律用显式滤镜（此处 loudnorm，必要时可叠加 ``volume=1.5``），
        **不要**使用 ``afade=t=out``，它会把整段压成静音(-91dB)。

    返回:
        ffmpeg 参数字符串列表，含 ``-af loudnorm=...``。
    """
    return ["-y", "-i", src, "-af", _LOUDNORM, dst]


def build_extract_cmd(video: str, dst: str) -> List[str]:
    """构建“从视频提取音频”命令。

    参数:
        video: 源视频文件。
        dst:   输出音频文件路径（扩展名决定编码）。

    实现说明：
        根据 ``dst`` 扩展名选择编码重新编码（保证容器兼容），
        用 ``-vn`` 丢弃视频流，仅保留音轨。

    返回:
        ffmpeg 参数字符串列表，含 ``-vn`` 与对应 ``-acodec``。
    """
    ext = os.path.splitext(dst)[1].lower().lstrip(".") or "mp3"
    codec = _CODEC_FOR_EXT.get(ext)
    if codec is None:  # 未知扩展名默认转 mp3
        dst = os.path.splitext(dst)[0] + ".mp3"
        codec = "libmp3lame"
    return ["-y", "-i", video, "-vn", "-acodec", codec, dst]


def build_concat_cmd(filelist: List[str], dst: str, list_path: Optional[str] = None):
    """构建“多文件合并”命令（concat demuxer）。

    参数:
        filelist:  待合并的文件路径列表（顺序即合并顺序）。
        dst:       合并后的输出文件路径。
        list_path: 临时 list 文件位置；``None`` 时自动用 tempfile 创建。

    实现说明（全哥经验）：
        使用 concat demuxer（``-f concat``）而非 ``aloop`` —— 本机 aloop 失效。
        生成的 list 文件每行写入 ``file '绝对路径'``，路径统一转正斜杠并
        转义单引号，避免 Windows 反斜杠被当作转义符。

    返回:
        ``(args, list_path)`` 二元组：
            args       -- ffmpeg 参数字符串列表；
            list_path  -- 生成的 list 文件路径（用完可由调用方删除）。

    异常:
        ValueError: filelist 为空。
    """
    files = [os.path.abspath(f) for f in filelist if f]
    if not files:
        raise ValueError("filelist 为空，无法合并。")
    if list_path is None:
        fd, list_path = tempfile.mkstemp(prefix="audiotool_concat_", suffix=".txt")
        os.close(fd)
    with open(list_path, "w", encoding="utf-8") as fh:
        for f in files:
            # 转正斜杠，避免 \ 被 ffmpeg 当作转义；单引号转义为 \'
            safe = f.replace("\\", "/").replace("'", "\\'")
            fh.write(f"file '{safe}'\n")
    ext = os.path.splitext(dst)[1].lower().lstrip(".") or "mp3"
    if ext not in AUDIO_FORMATS:
        ext = "mp3"
        dst = os.path.splitext(dst)[0] + ".mp3"
    args = ["-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", dst]
    return args, list_path
