"""audiotool 图形界面入口（Tkinter，UI 中文）。

功能：选文件或文件夹 → 勾选批量操作：
    ① 格式转换（mp3/wav/ogg/flac，ffmpeg）
    ② 裁剪（起止时间 mm:ss 或秒）
    ③ 音量归一（loudnorm 滤镜）
    ④ 从视频提取音频
    ⑤ 多文件合并（concat demuxer）
输出统一写入 ``<输入根>/audiotool_out/``。

说明：
    * 本文件仅在 ``if __name__ == '__main__':`` 守卫内实例化 Tk()，
      无显示器环境导入本模块不会创建 GUI（冒烟测试只 import core）。
    * 实际音视频处理全部委托给 core.py（subprocess 调 ffmpeg），
      本文件只负责 UI、参数收集与流水编排。

运行方式：
    python main.py
（需系统已安装 ffmpeg 并加入 PATH，或设置 AUDIOTOOL_FFMPEG 环境变量）
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

import core

# 视频/音频扩展名（用于区分“提取音频”适用对象）
VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".webm", ".m4v", ".mpeg", ".mpg")
AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".wma", ".opus")


def _is_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


def _is_audio(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in AUDIO_EXTS


class AudiotoolApp:
    """audiotool 主窗口与处理逻辑。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("audiotool · 音频加工工具")
        root.geometry("720x640")
        root.resizable(True, True)

        self.src_mode = tk.StringVar(value="file")  # file | folder
        self.input_paths: list[str] = []            # 当前选中的源路径
        self.out_dir = tk.StringVar(value="")
        self.running = False

        # 操作开关
        self.opt_convert = tk.BooleanVar()
        self.opt_trim = tk.BooleanVar()
        self.opt_normalize = tk.BooleanVar()
        self.opt_extract = tk.BooleanVar()
        self.opt_merge = tk.BooleanVar()

        # 参数
        self.fmt_var = tk.StringVar(value="mp3")
        self.start_var = tk.StringVar(value="0:00")
        self.end_var = tk.StringVar(value="")

        self._build_widgets()

    # ------------------------------------------------------------------ UI
    def _build_widgets(self) -> None:
        pad = {"padx": 8, "pady": 4}

        # ---- 输入区 ----
        f_in = ttk.LabelFrame(self.root, text="1. 选择输入（文件或文件夹）")
        f_in.pack(fill="x", **pad)
        ttk.Radiobutton(f_in, text="单个文件", variable=self.src_mode, value="file",
                        command=self._on_mode_change).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(f_in, text="整个文件夹", variable=self.src_mode, value="folder",
                        command=self._on_mode_change).grid(row=0, column=1, sticky="w")
        ttk.Button(f_in, text="浏览...", command=self._browse).grid(row=0, column=2, sticky="w")
        self.src_label = ttk.Label(f_in, text="（未选择）", foreground="#555")
        self.src_label.grid(row=1, column=0, columnspan=3, sticky="w")

        # ---- 操作区 ----
        f_op = ttk.LabelFrame(self.root, text="2. 勾选批量操作与参数")
        f_op.pack(fill="x", **pad)

        ttk.Checkbutton(f_op, text="① 格式转换", variable=self.opt_convert).grid(row=0, column=0, sticky="w")
        ttk.Label(f_op, text="目标格式:").grid(row=0, column=1, sticky="w")
        ttk.Combobox(f_op, textvariable=self.fmt_var, width=10,
                     values=list(core.AUDIO_FORMATS), state="readonly").grid(row=0, column=2, sticky="w")

        ttk.Checkbutton(f_op, text="② 裁剪", variable=self.opt_trim).grid(row=1, column=0, sticky="w")
        ttk.Label(f_op, text="开始:").grid(row=1, column=1, sticky="w")
        ttk.Entry(f_op, textvariable=self.start_var, width=10).grid(row=1, column=2, sticky="w")
        ttk.Label(f_op, text="结束(mm:ss或秒, 留空到结尾):").grid(row=1, column=3, sticky="w")
        ttk.Entry(f_op, textvariable=self.end_var, width=12).grid(row=1, column=4, sticky="w")

        ttk.Checkbutton(f_op, text="③ 音量归一(loudnorm)", variable=self.opt_normalize).grid(row=2, column=0, sticky="w")
        ttk.Checkbutton(f_op, text="④ 从视频提取音频", variable=self.opt_extract).grid(row=2, column=1, columnspan=2, sticky="w")
        ttk.Checkbutton(f_op, text="⑤ 多文件合并(concat)", variable=self.opt_merge).grid(row=3, column=0, columnspan=2, sticky="w")

        # ---- 输出区 ----
        f_out = ttk.LabelFrame(self.root, text="3. 输出目录（默认 <输入>/audiotool_out/）")
        f_out.pack(fill="x", **pad)
        ttk.Entry(f_out, textvariable=self.out_dir).pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(f_out, text="浏览...", command=self._browse_out).pack(side="left")

        # ---- 执行区 ----
        f_run = ttk.Frame(self.root)
        f_run.pack(fill="x", **pad)
        self.run_btn = ttk.Button(f_run, text="开始处理", command=self._on_run)
        self.run_btn.pack(side="left")
        self.stop_btn = ttk.Button(f_run, text="停止", command=self._request_stop, state="disabled")
        self.stop_btn.pack(side="left", padx=(6, 0))
        self.progress = ttk.Progressbar(f_run, mode="indeterminate")
        self.progress.pack(side="left", fill="x", expand=True, padx=(6, 0))

        # ---- 日志区 ----
        f_log = ttk.LabelFrame(self.root, text="日志 / 进度")
        f_log.pack(fill="both", expand=True, **pad)
        self.log = scrolledtext.ScrolledText(f_log, height=14, state="disabled",
                                             font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)

    # ------------------------------------------------------------------ 交互
    def _on_mode_change(self) -> None:
        self.input_paths = []
        self._refresh_src_label()

    def _browse(self) -> None:
        if self.src_mode.get() == "file":
            paths = filedialog.askopenfilenames(
                title="选择音频/视频文件（可多选）",
                filetypes=[("媒体文件", "*.mp3 *.wav *.ogg *.flac *.m4a *.aac *.mp4 *.mkv *.avi *.mov *.webm"),
                           ("所有文件", "*.*")])
            self.input_paths = list(paths)
        else:
            d = filedialog.askdirectory(title="选择文件夹（将处理其中所有媒体文件）")
            if d:
                self.input_paths = [d]
        self._refresh_src_label()

    def _refresh_src_label(self) -> None:
        if not self.input_paths:
            self.src_label.config(text="（未选择）")
            self.out_dir.set("")
            return
        if self.src_mode.get() == "folder":
            self.src_label.config(text=f"文件夹: {self.input_paths[0]}")
            self.out_dir.set(os.path.join(self.input_paths[0], "audiotool_out"))
        else:
            n = len(self.input_paths)
            self.src_label.config(text=f"已选 {n} 个文件: {self.input_paths[0]}" + (" ..." if n > 1 else ""))
            # 多文件以首个文件所在目录作为输出根
            root_dir = os.path.dirname(self.input_paths[0]) if n else ""
            self.out_dir.set(os.path.join(root_dir, "audiotool_out") if root_dir else "audiotool_out")

    def _browse_out(self) -> None:
        d = filedialog.askdirectory(title="选择输出目录")
        if d:
            self.out_dir.set(d)

    def _log(self, msg: str) -> None:
        self.root.after(0, self._append_log, msg)

    def _append_log(self, msg: str) -> None:
        self.log.config(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _request_stop(self) -> None:
        self.running = False
        self._log("⚠ 已请求停止，将在当前文件处理完后退出。")

    # ------------------------------------------------------------------ 执行
    def _on_run(self) -> None:
        if self.running:
            return
        if not self.input_paths:
            messagebox.showwarning("提示", "请先选择输入文件或文件夹。")
            return
        out = self.out_dir.get().strip()
        if not out:
            messagebox.showwarning("提示", "输出目录为空。")
            return
        # 收集勾选的操作
        ops = self._collect_ops()
        if not ops:
            messagebox.showwarning("提示", "请至少勾选一项操作。")
            return
        os.makedirs(out, exist_ok=True)
        self.running = True
        self.run_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.progress.start(20)
        # 后台线程执行，避免界面卡死
        threading.Thread(target=self._worker, args=(out, ops), daemon=True).start()

    def _collect_ops(self) -> dict:
        """把界面勾选状态整理成参数字典。"""
        fmt = self.fmt_var.get().lower()
        return {
            "convert": self.opt_convert.get(),
            "fmt": fmt if fmt in core.AUDIO_FORMATS else "mp3",
            "trim": self.opt_trim.get(),
            "start": self.start_var.get(),
            "end": self.end_var.get(),
            "normalize": self.opt_normalize.get(),
            "extract": self.opt_extract.get(),
            "merge": self.opt_merge.get(),
        }

    def _resolve_files(self) -> list[str]:
        """根据模式解析出待处理文件列表。"""
        if self.src_mode.get() == "folder":
            folder = self.input_paths[0]
            files = []
            for name in sorted(os.listdir(folder)):
                p = os.path.join(folder, name)
                if os.path.isfile(p) and (name.lower().endswith(VIDEO_EXTS + AUDIO_EXTS)):
                    files.append(p)
            return files
        return list(self.input_paths)

    def _worker(self, out: str, ops: dict) -> None:
        """后台工作线程：编排并执行各操作。"""
        try:
            if not core.ffmpeg_path():
                self._log("✗ 未检测到 ffmpeg，无法执行。请安装并加入 PATH，"
                          "或设置 AUDIOTOOL_FFMPEG 环境变量。")
                return
            if ops["merge"]:
                self._run_merge(out, ops)
            else:
                files = self._resolve_files()
                if not files:
                    self._log("✗ 未找到可处理的媒体文件。")
                    return
                total = len(files)
                for i, src in enumerate(files, 1):
                    if not self.running:
                        self._log("已停止。")
                        break
                    self._log(f"[{i}/{total}] 处理: {os.path.basename(src)}")
                    try:
                        self._process_one(src, out, ops)
                    except Exception as exc:  # 单文件失败不中断整体
                        self._log(f"  ✗ 失败: {exc}")
                self._log("✓ 处理完成。输出目录: " + out)
        except Exception as exc:
            self._log(f"✗ 发生错误: {exc}")
        finally:
            self.root.after(0, self._finish_run)

    def _finish_run(self) -> None:
        self.running = False
        self.run_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.progress.stop()

    def _run_merge(self, out: str, ops: dict) -> None:
        """合并模式：把所有输入文件 concat 成一个输出文件。"""
        files = self._resolve_files()
        if len(files) < 2:
            self._log("✗ 合并模式需要至少 2 个文件。")
            return
        fmt = ops["fmt"] if ops["convert"] else "mp3"
        dst = os.path.join(out, f"merged.{fmt}")
        self._log(f"合并 {len(files)} 个文件 → {dst}")
        args, list_path = core.build_concat_cmd(files, dst)
        try:
            rc, _, stderr = core.run_ffmpeg(args)
            if rc == 0:
                self._log("  ✓ 合并成功。")
            else:
                self._log("  ✗ ffmpeg 返回非 0：\n" + stderr[-2000:])
        finally:
            if list_path and os.path.exists(list_path):
                try:
                    os.remove(list_path)
                except OSError:
                    pass

    def _process_one(self, src: str, out: str, ops: dict) -> None:
        """对单个文件执行流水线：提取 → 转换 → 裁剪 → 归一。"""
        base = os.path.splitext(os.path.basename(src))[0]
        current = src
        is_video = _is_video(src)

        # ④ 从视频提取音频
        if ops["extract"] and is_video:
            ext = ops["fmt"] if ops["convert"] else "mp3"
            dst = os.path.join(out, f"{base}_extracted.{ext}")
            args = core.build_extract_cmd(current, dst)
            self._run_step("提取音频", args)
            current = dst

        # ① 格式转换
        if ops["convert"]:
            dst = os.path.join(out, f"{base}.{ops['fmt']}")
            args = core.build_convert_cmd(current, dst, ops["fmt"])
            self._run_step("格式转换", args)
            current = dst

        # ② 裁剪
        if ops["trim"]:
            end = ops["end"].strip() or None
            dst = os.path.join(out, f"{os.path.splitext(os.path.basename(current))[0]}_trim{os.path.splitext(current)[1]}")
            args = core.build_trim_cmd(current, dst, ops["start"], end)
            self._run_step("裁剪", args)
            current = dst

        # ③ 音量归一
        if ops["normalize"]:
            dst = os.path.join(out, f"{os.path.splitext(os.path.basename(current))[0]}_norm{os.path.splitext(current)[1]}")
            args = core.build_normalize_cmd(current, dst)
            self._run_step("音量归一", args)
            current = dst

        self._log(f"  → 输出: {current}")

    def _run_step(self, name: str, args: list[str]) -> None:
        """执行单个 ffmpeg 步骤，记录日志。"""
        self._log(f"  · {name}: ffmpeg {' '.join(args)}")
        if not self.running:
            raise RuntimeError("已停止")
        rc, _, stderr = core.run_ffmpeg(args)
        if rc != 0:
            raise RuntimeError(f"{name} 失败 (ffmpeg rc={rc}): {stderr[-1000:]}")

    # ------------------------------------------------------------------ 入口
    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    root = tk.Tk()
    app = AudiotoolApp(root)
    app.run()


if __name__ == "__main__":
    main()
