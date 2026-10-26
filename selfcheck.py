# -*- coding: utf-8 -*-
"""audiotool · 无头自检（不启动 tkinter，不调用 ffmpeg）。

验证 core.py 的纯逻辑：
1. 时间解析 _to_seconds 与裁剪命令的时长计算；
2. 转换 / 归一 / 提取 / 合并命令的参数拼接与非法输入校验；
3. concat 列表文件的路径转义（反斜杠转正斜杠、单引号转义）。

ffmpeg 是否存在不影响本自检。
"""

from __future__ import annotations

import os
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import core  # noqa: E402


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def expect_value_error(func, *args, **kwargs):
    try:
        func(*args, **kwargs)
    except ValueError:
        return
    raise AssertionError(f"{func.__name__} 未对非法参数抛出 ValueError")


def check_time_parsing() -> None:
    check(core._to_seconds(None) == 0.0, "None 应解析为 0 秒")
    check(core._to_seconds("") == 0.0, "空字符串应解析为 0 秒")
    check(core._to_seconds(2.5) == 2.5, "数字秒数解析错误")
    check(core._to_seconds("90") == 90.0, "纯秒数字符串解析错误")
    check(core._to_seconds("1:30") == 90.0, "mm:ss 解析错误")
    check(core._to_seconds("01:02:03") == 3723.0, "hh:mm:ss 解析错误")
    expect_value_error(core._to_seconds, "1:xx")


def check_commands() -> None:
    src = os.path.join("tmp", "in.wav")
    dst = os.path.join("tmp", "out.MP3")

    convert = core.build_convert_cmd(src, dst, "mp3")
    check(convert == ["-y", "-i", src, os.path.join("tmp", "out.mp3")],
          f"转换命令拼接错误: {convert!r}")
    expect_value_error(core.build_convert_cmd, src, dst, "aac")

    trim = core.build_trim_cmd(src, dst, "0:30", "1:00")
    check(trim == ["-y", "-ss", "30.000", "-i", src,
                   "-t", "30.000", "-c", "copy", dst],
          f"裁剪命令拼接错误: {trim!r}")
    trim_open_end = core.build_trim_cmd(src, dst, 10)
    check("-t" not in trim_open_end, "未指定结束时间时不应出现 -t")
    check(trim_open_end[trim_open_end.index("-ss") + 1] == "10.000",
          "起始时间格式化错误")
    expect_value_error(core.build_trim_cmd, src, dst, -1)
    expect_value_error(core.build_trim_cmd, src, dst, 10, 10)

    normalize = core.build_normalize_cmd(src, dst)
    check("-af" in normalize, "归一命令缺少 -af")
    filter_expr = normalize[normalize.index("-af") + 1]
    check("loudnorm" in filter_expr, "归一命令未使用 loudnorm")
    check("afade" not in filter_expr, "归一命令误用了 afade")

    extract = core.build_extract_cmd("clip.mp4", "audio.flac")
    check(extract == ["-y", "-i", "clip.mp4", "-vn", "-acodec", "flac",
                      "audio.flac"], f"提取音频命令错误: {extract!r}")
    unknown = core.build_extract_cmd("clip.mp4", "audio.xyz")
    check(unknown[-1] == "audio.mp3" and "libmp3lame" in unknown,
          f"未知扩展名未回退 mp3: {unknown!r}")


def check_concat() -> None:
    with tempfile.TemporaryDirectory(prefix="audiotool_selfcheck_") as tmp:
        first = os.path.join(tmp, "alpha's take.wav")
        second = os.path.join(tmp, "beta take.wav")
        for path in (first, second):
            with open(path, "wb") as fh:
                fh.write(b"RIFF")

        out = os.path.join(tmp, "merged.mp3")
        list_path = os.path.join(tmp, "concat.txt")
        args, returned_list = core.build_concat_cmd([first, second], out,
                                                    list_path=list_path)
        check(returned_list == list_path, "concat 未使用传入的 list 路径")
        check(args[:6] == ["-y", "-f", "concat", "-safe", "0", "-i"],
              f"concat 参数错误: {args!r}")
        check(args[-1].endswith("merged.mp3"), "concat 输出路径错误")

        with open(list_path, "r", encoding="utf-8") as fh:
            lines = [line.rstrip("\n") for line in fh]
        check(len(lines) == 2, f"concat 列表行数错误: {lines!r}")
        for line, path in zip(lines, (first, second)):
            check(line.startswith("file '") and line.endswith("'"),
                  f"concat 列表行格式错误: {line!r}")
            # 单引号必须转义；去掉转义序列后不应再残留反斜杠
            check("\\" not in line.replace("\\'", ""),
                  f"concat 列表仍含未转义反斜杠: {line!r}")
            expected = path.replace("\\", "/").replace("'", "\\'")
            check(expected in line, f"concat 列表路径错误: {line!r}")

        expect_value_error(core.build_concat_cmd, [], out,
                           list_path=os.path.join(tmp, "empty.txt"))


def main() -> int:
    try:
        check_time_parsing()
        check_commands()
        check_concat()
        print(
            "selfcheck ok: _to_seconds 解析 5 类时间输入（None/数字/秒字符串/"
            "mm:ss/hh:mm:ss）；转换/裁剪/归一/提取/合并 "
            "5 类命令参数正确、非法格式报 ValueError；concat 列表路径转义正确"
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
