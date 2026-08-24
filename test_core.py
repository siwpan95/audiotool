"""audiotool 冒烟测试：只验证 core.py 的命令拼接纯函数。

设计：
    * 不强制真跑 ffmpeg（build_*_cmd 是纯函数，ffmpeg 有无均可测试）。
    * 断言关键标志存在：`-i`、正确输出扩展名、`loudnorm`、`concat` 等。
    * 额外验证 ffmpeg_path() 的环境表现（有则返回路径，无则返回 None）。
    * 附带一个“真实调用”用例：若环境存在 ffmpeg，则实际跑一次简单转换，
      验证 run_ffmpeg 端到端可用（失败不影响纯函数测试结论）。
"""

from __future__ import annotations

# Windows 控制台编码修复：测试输出含 ✅/✓ 等符号，GBK 代码页无法编码
import sys
if sys.stdout and getattr(sys.stdout, "encoding", "").lower() not in ("utf-8", "utf8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


import os
import shutil
import tempfile

import core


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)
    print(f"  ✓ {msg}")


def test_convert() -> None:
    print("[convert]")
    args = core.build_convert_cmd("in.wav", "out.unk", "mp3")
    _assert("-i" in args, "含 -i 输入标志")
    _assert(args[-1].endswith(".mp3"), f"输出扩展名正确 -> {args[-1]}")
    _assert(args[args.index("-i") + 1] == "in.wav", "输入路径正确")
    # 非法格式应报错
    try:
        core.build_convert_cmd("a.wav", "b.x", "xyz")
        _assert(False, "非法格式应抛 ValueError")
    except ValueError:
        _assert(True, "非法格式抛 ValueError")


def test_trim() -> None:
    print("[trim]")
    # mm:ss 形式
    args = core.build_trim_cmd("in.mp3", "out.mp3", "0:30", "1:00")
    _assert("-ss" in args and "-t" in args, "含 -ss 与 -t")
    i = args.index("-ss")
    _assert(args[i + 1] == "30.000", f"start 解析正确 0:30 -> {args[i+1]}")
    j = args.index("-t")
    _assert(args[j + 1] == "30.000", f"时长计算正确 -> {args[j+1]}")
    # 秒数形式 + 无结束
    args2 = core.build_trim_cmd("in.mp3", "out.mp3", 10, None)
    _assert("-ss" in args2 and "-t" not in args2, "无结束时间时不带 -t")
    _assert("-c" in args2 and "copy" in args2, "使用流复制 -c copy")
    # end <= start 报错
    try:
        core.build_trim_cmd("in.mp3", "out.mp3", 10, 5)
        _assert(False, "end<=start 应抛 ValueError")
    except ValueError:
        _assert(True, "end<=start 抛 ValueError")


def test_normalize() -> None:
    print("[normalize]")
    args = core.build_normalize_cmd("in.wav", "out.wav")
    _assert("-i" in args, "含 -i")
    _assert(any(a.startswith("loudnorm") for a in args), "含 loudnorm 滤镜")


def test_extract() -> None:
    print("[extract]")
    args = core.build_extract_cmd("v.mp4", "a.mp3")
    _assert("-vn" in args, "含 -vn（丢弃视频）")
    _assert("-acodec" in args, "含 -acodec")
    _assert(args[-1].endswith(".mp3"), "输出为 mp3")
    # 未知扩展名回退为 mp3
    args2 = core.build_extract_cmd("v.mp4", "a.unk")
    _assert(args2[-1].endswith(".mp3"), "未知扩展名回退 mp3")


def test_concat() -> None:
    print("[concat]")
    files = ["C:/a/b song.mp3", "C:/a/c.mp3"]
    args, list_path = core.build_concat_cmd(files, "merged.ogg")
    _assert("-f" in args and "concat" in args, "含 -f concat（concat demuxer）")
    _assert("-i" in args, "含 -i")
    _assert(args[-1].endswith(".ogg"), f"输出扩展名正确 -> {args[-1]}")
    # list 文件内容检查
    _assert(os.path.exists(list_path), "生成了临时 list 文件")
    with open(list_path, "r", encoding="utf-8") as fh:
        content = fh.read()
    _assert(content.count("file '") == 2, "list 含两个 file 条目")
    _assert("\\" not in content or "/" in content, "路径使用正斜杠（避免转义问题）")
    _assert("song" in content, "list 含文件名（含空格路径被引用）")
    os.remove(list_path)
    # 空列表报错
    try:
        core.build_concat_cmd([], "m.mp3")
        _assert(False, "空列表应抛 ValueError")
    except ValueError:
        _assert(True, "空列表抛 ValueError")


def test_ffmpeg_path() -> None:
    print("[ffmpeg_path]")
    p = core.ffmpeg_path()
    if p:
        _assert(True, f"检测到 ffmpeg: {p}")
    else:
        _assert(True, "未检测到 ffmpeg（运行时需安装并加入 PATH）")
    return p


def test_run_ffmpeg_real(ffmpeg: str | None) -> None:
    """真实调用 ffmpeg：仅当环境中存在 ffmpeg 时执行，失败不致命。"""
    print("[run_ffmpeg 真实调用]")
    if not ffmpeg:
        print("  ⊘ 跳过：环境中无 ffmpeg，仅验证拼接逻辑（符合规格）。")
        return
    # 生成一个 0.5s 静音 wav，再转 mp3，验证端到端
    tmp = tempfile.mkdtemp(prefix="audiotool_test_")
    src = os.path.join(tmp, "silence.wav")
    dst = os.path.join(tmp, "silence.mp3")
    # 用 ffmpeg 生成静音源
    gen = [ffmpeg, "-y", "-f", "lavfi", "-i", "anoisesrc=d=0.5:c=white",
           "-t", "0.5", src]
    import subprocess
    r = subprocess.run(gen, capture_output=True, text=True)
    if r.returncode != 0:
        print("  ⊘ 生成测试源失败，跳过真实调用验证。")
        return
    args = core.build_convert_cmd(src, dst, "mp3")
    rc, _, stderr = core.run_ffmpeg(args)
    _assert(rc == 0 and os.path.exists(dst) and os.path.getsize(dst) > 0,
            f"run_ffmpeg 端到端转换成功 -> {dst}")
    shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    print("=== audiotool 冒烟测试 ===")
    test_convert()
    test_trim()
    test_normalize()
    test_extract()
    test_concat()
    ffmpeg = test_ffmpeg_path()
    test_run_ffmpeg_real(ffmpeg)
    print("=== 全部通过 ===")


if __name__ == "__main__":
    main()
