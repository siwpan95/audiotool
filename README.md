> 📦 **已归档（Archived — 仅作参考）**
> 本仓库已收入归档仓 **music-prototypes**（代码与完整 git 历史一并迁入，原仓冻结不再开发）。
> 历史分支见归档仓的 `archive/audiotool` 分支；活跃维护请前往 **music-prototypes**。
> _This repo is archived into music-prototypes; development continues there. Do not commit here._

# audiotool · 音频加工工具

> 仓库：<https://gitee.com/siwpan/audiotool> ｜ 许可：MIT（见 [LICENSE](LICENSE)）
> 注：文中 <PATH> 为路径占位符，请替换为你本机实际的目录 / 可执行文件路径。

一个**自包含**的 Windows 桌面小工具（Tkinter GUI），用于批量处理音频/视频：
选文件或文件夹 → 勾选操作 → 一键输出到 `<输入>/audiotool_out/`。

> 自包含原则：本工具位于 `<PATH>`（独立仓 siwpan/audiotool），独立运行，不 import 其他工具目录，
> 不依赖中心化共享核（复制优于共享）。

---

## 功能

| 操作 | 说明 | 实现 |
|------|------|------|
| ① 格式转换 | mp3 / wav / ogg / flac 互转 | ffmpeg 重新编码 |
| ② 裁剪 | 起止时间，支持 `mm:ss` 或秒 | `-ss` + `-t` 流复制 |
| ③ 音量归一 | 统一响度到播客常用目标 | `loudnorm` 滤镜 |
| ④ 从视频提取音频 | 丢弃视频流保留音轨 | `-vn` + 对应编码 |
| ⑤ 多文件合并 | 顺序拼接成一个文件 | concat demuxer |

输出统一写入 `<输入根>/audiotool_out/`（可在界面修改）。

---

## 运行方式

```bat
"python" main.py
```

前置条件：
- 系统已安装 **ffmpeg** 并加入 PATH，或设置环境变量 `AUDIOTOOL_FFMPEG` 指向 ffmpeg.exe。
- 验证 ffmpeg：`ffmpeg -version`。

---

## 使用步骤

1. **选择输入**：选「单个文件」（可多选）或「整个文件夹」。
2. **勾选操作并填参数**：
   - 格式转换：选目标格式。
   - 裁剪：填开始/结束时间（如 `0:30`、`1:00`；结束留空表示到结尾）。
   - 音量归一 / 从视频提取音频 / 多文件合并：直接勾选。
3. **确认输出目录**（默认 `<输入>/audiotool_out/`）。
4. 点「开始处理」。日志区显示进度，可随时「停止」。

> 合并模式：把所有选中文件按顺序 concat 成一个 `merged.<fmt>`；
> 非合并模式：对每个文件依次执行 提取→转换→裁剪→归一 流水线。

---

## 全哥踩坑经验（已内建于实现）

- **不要用 `afade=t=out`** 做淡出/混音：它会把整段压成静音（-91dB）。
  音量增益一律用显式滤镜，如 `volume=1.5`。本项目归一用 `loudnorm`，避免踩坑。
- **合并用 concat demuxer**，不用 `aloop`（本机 aloop 失效）。
- 裁剪默认 `-c copy` 流复制保质量；对部分有损格式非帧级精确（见限制）。

---

## 已知限制

- **裁剪精度**：`-c copy` 方式对 mp3 等有损格式不是帧级精确，起止点会吸附到关键帧。
  如需精确裁剪，需改为重新编码（可后续扩展）。
- **合并一致性**：concat demuxer 要求各文件编码/采样率/声道数一致，否则可能失败；
  建议先统一转换为同格式再合并。
- **无显示器环境**：GUI 需 Tk 与显示器；纯逻辑（core.py 的 `build_*_cmd`）可脱离 GUI 测试。
- **ffmpeg 为外部依赖**：本工具不打包 ffmpeg，缺失时会明确提示而非静默失败。

---

## 测试

冒烟测试只验证 `core.py` 的**命令拼接纯函数**（不强制真跑 ffmpeg）：

```bat
"python" test_core.py
```

覆盖：各 `build_*_cmd` 生成参数含关键标志（`-i`、正确输出扩展名、`loudnorm`、
`concat` 等）；`ffmpeg_path()` 在 PATH 含 ffmpeg 时返回路径，否则返回 `None`。
