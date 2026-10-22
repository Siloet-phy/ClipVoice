"""
ClipVoice - 智能剪切板管理器
功能：文字/图片复制粘贴 | 历史记录持久化 | 语音录入 | 本地语音转文字
UI：ttkbootstrap 现代主题
语音：FunASR Paraformer-zh / sherpa-onnx SenseVoice（本地离线）
"""

__version__ = "1.0.0"

import tkinter as tk
from tkinter import ttk, messagebox
import ttkbootstrap as ttkb
import sqlite3
import threading
import io
import os
import time
import struct
from PIL import Image, ImageTk
import sounddevice as sd
import numpy as np
import win32clipboard
import win32con

# ==================== 路径配置 ====================
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
RECORDINGS_DIR = os.path.join(DATA_DIR, "recordings")
DB_PATH = os.path.join(DATA_DIR, "clipboard.db")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

os.makedirs(RECORDINGS_DIR, exist_ok=True)

# 语音引擎：自动检测可用引擎
STT_ENGINE = "none"  # "funasr" | "sherpa" | "none"

try:
    from funasr import AutoModel
    STT_ENGINE = "funasr"
except ImportError:
    try:
        import sherpa_onnx
        STT_ENGINE = "sherpa"
    except ImportError:
        pass


# ==================== 剪切板工具（win32） ====================
class ClipboardHelper:
    """使用 win32clipboard 原生 API 读写系统剪切板，支持文字和图片。"""

    @staticmethod
    def get_text():
        try:
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                    return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                elif win32clipboard.IsClipboardFormatAvailable(win32con.CF_TEXT):
                    return win32clipboard.GetClipboardData(win32con.CF_TEXT).decode("utf-8", errors="ignore")
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            return None

    @staticmethod
    def get_image():
        try:
            win32clipboard.OpenClipboard()
            try:
                if win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB):
                    data = win32clipboard.GetClipboardData(win32con.CF_DIB)
                    return ClipboardHelper._dib_to_image(data)
            finally:
                win32clipboard.CloseClipboard()
        except Exception:
            return None

    @staticmethod
    def _dib_to_image(dib_data):
        import tempfile
        file_header = b"BM"
        file_size = 14 + len(dib_data)
        header = file_header + struct.pack("<I", file_size) + b"\x00\x00\x00\x00" + struct.pack("<I", 14)
        tmp = os.path.join(tempfile.gettempdir(), "_clipboard_tmp.bmp")
        with open(tmp, "wb") as f:
            f.write(header + dib_data)
        try:
            img = Image.open(tmp)
            img.load()
            return img.copy()
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    @staticmethod
    def set_text(text):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            finally:
                win32clipboard.CloseClipboard()
            return True
        except Exception:
            return False

    @staticmethod
    def set_image(pil_image):
        try:
            img = pil_image.convert("RGBA")
            buf = io.BytesIO()
            img.save(buf, format="BMP")
            dib_data = buf.getvalue()[14:]
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32con.CF_DIB, dib_data)
            finally:
                win32clipboard.CloseClipboard()
            return True
        except Exception:
            return False

    @staticmethod
    def has_changed(last_text, last_image_hash):
        current_text = ClipboardHelper.get_text()
        current_image = ClipboardHelper.get_image()
        new_hash = None
        if current_image:
            thumb = current_image.copy()
            thumb.thumbnail((64, 64))
            new_hash = hash(thumb.tobytes())
        text_changed = current_text != last_text and current_text is not None
        image_changed = new_hash != last_image_hash and new_hash is not None
        if text_changed or image_changed:
            return True, current_text, current_image, new_hash
        return False, current_text, current_image, new_hash


# ==================== 数据库 ====================
class Database:
    def __init__(self, db_path):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.lock = threading.Lock()
        self._init()

    def _init(self):
        with self.lock:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS clipboard_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    text_content TEXT,
                    image_data BLOB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS voice_recordings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    audio_path TEXT NOT NULL,
                    text_content TEXT,
                    duration REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.conn.commit()

    def save_clipboard(self, item_type, text=None, image_data=None):
        with self.lock:
            self.conn.execute(
                "INSERT INTO clipboard_history (type, text_content, image_data) VALUES (?,?,?)",
                (item_type, text, image_data),
            )
            self.conn.commit()

    def get_history(self, limit=200):
        with self.lock:
            return self.conn.execute(
                "SELECT id, type, text_content, created_at FROM clipboard_history "
                "ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()

    def get_text_by_id(self, item_id):
        with self.lock:
            row = self.conn.execute(
                "SELECT text_content FROM clipboard_history WHERE id=?", (item_id,)
            ).fetchone()
            return row[0] if row else None

    def get_image(self, item_id):
        with self.lock:
            row = self.conn.execute(
                "SELECT image_data FROM clipboard_history WHERE id=?", (item_id,)
            ).fetchone()
            return row[0] if row else None

    def delete_item(self, item_id):
        with self.lock:
            self.conn.execute("DELETE FROM clipboard_history WHERE id=?", (item_id,))
            self.conn.commit()

    def search(self, keyword):
        with self.lock:
            return self.conn.execute(
                "SELECT id, type, text_content, created_at FROM clipboard_history "
                "WHERE text_content LIKE ? ORDER BY created_at DESC LIMIT 50",
                (f"%{keyword}%",),
            ).fetchall()

    def save_voice(self, audio_data, sample_rate, text=None, duration=0):
        import soundfile as sf
        ts = int(time.time() * 1000)
        path = os.path.join(RECORDINGS_DIR, f"voice_{ts}.wav")
        sf.write(path, audio_data, sample_rate)
        with self.lock:
            self.conn.execute(
                "INSERT INTO voice_recordings (audio_path, text_content, duration) VALUES (?,?,?)",
                (path, text, duration),
            )
            self.conn.commit()
        return path

    def get_voices(self, limit=50):
        with self.lock:
            return self.conn.execute(
                "SELECT id, audio_path, text_content, duration, created_at "
                "FROM voice_recordings ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()


# ==================== 录音器 ====================
class AudioRecorder:
    def __init__(self, sample_rate=16000):
        self.sample_rate = sample_rate
        self.stream = None
        self.chunks = []
        self.recording = False

    def _callback(self, indata, frames, time_info, status):
        if self.recording:
            self.chunks.append(indata.copy())

    def start(self):
        self.chunks = []
        self.recording = True
        self.stream = sd.InputStream(samplerate=self.sample_rate, channels=1, callback=self._callback)
        self.stream.start()

    def stop(self):
        self.recording = False
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        if self.chunks:
            return np.concatenate(self.chunks, axis=0)
        return None


# ==================== 语音识别引擎 ====================
class SpeechRecognizer:
    """自动选择可用的本地语音识别引擎。"""

    _funasr_model = None
    _sherpa_recognizer = None
    _lock = threading.Lock()

    @classmethod
    def is_available(cls):
        return STT_ENGINE != "none"

    @classmethod
    def engine_name(cls):
        if STT_ENGINE == "funasr":
            return "FunASR Paraformer-zh"
        elif STT_ENGINE == "sherpa":
            return "sherpa-onnx SenseVoice"
        return "无"

    @classmethod
    def _init_funasr(cls):
        if cls._funasr_model is None:
            with cls._lock:
                if cls._funasr_model is None:
                    cls._funasr_model = AutoModel(
                        model="paraformer-zh",
                        vad_model="fsmn-vad",
                        punc_model="ct-punc",
                        disable_update=True,
                    )

    @classmethod
    def _init_sherpa(cls):
        if cls._sherpa_recognizer is None:
            with cls._lock:
                if cls._sherpa_recognizer is None:
                    model_dir = os.path.join(
                        os.path.expanduser("~"),
                        ".cache", "dsh-voice", "models", "csukuangfj",
                        "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
                        "resolve", "main",
                    )
                    model_path = os.path.join(model_dir, "model.int8.onnx")
                    tokens_path = os.path.join(model_dir, "tokens.txt")
                    if not os.path.exists(model_path):
                        raise FileNotFoundError(f"SenseVoice 模型不存在: {model_path}")
                    import sherpa_onnx
                    cls._sherpa_recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                        model=model_path, tokens=tokens_path, language="zh", use_itn=True,
                    )

    @classmethod
    def recognize(cls, audio_data, sample_rate):
        if audio_data.ndim > 1:
            audio_data = audio_data.flatten()
        audio_float32 = audio_data.astype(np.float32)

        if STT_ENGINE == "funasr":
            cls._init_funasr()
            import tempfile, soundfile as sf
            tmp = os.path.join(tempfile.gettempdir(), "_clipvoice_stt.wav")
            sf.write(tmp, audio_float32, sample_rate)
            result = cls._funasr_model.generate(input=tmp)
            try:
                os.remove(tmp)
            except OSError:
                pass
            return result[0]["text"].strip() if result else ""

        elif STT_ENGINE == "sherpa":
            cls._init_sherpa()
            stream = cls._sherpa_recognizer.create_stream()
            stream.accept_waveform(sample_rate, audio_float32)
            cls._sherpa_recognizer.decode_stream(stream)
            return stream.result.text.strip()

        return ""


# ==================== 主应用 ====================
class ClipboardManager:
    def __init__(self, root):
        self.root = root
        self.root.title("ClipVoice - 智能剪切板管理器")
        self.root.geometry("860x640")
        self.root.minsize(700, 500)

        self.db = Database(DB_PATH)
        self.recorder = AudioRecorder()
        self.is_recording = False
        self.last_clip_text = ""
        self.last_image_hash = None
        self._suppress_poll = False

        self._build_ui()
        self._refresh_history()
        self._poll_clipboard()

        if SpeechRecognizer.is_available():
            threading.Thread(target=self._preload_stt, daemon=True).start()
        else:
            self._set_status("未检测到语音引擎，可安装 funasr 或 sherpa-onnx")

    def _preload_stt(self):
        try:
            if STT_ENGINE == "funasr":
                SpeechRecognizer._init_funasr()
            elif STT_ENGINE == "sherpa":
                SpeechRecognizer._init_sherpa()
            engine = SpeechRecognizer.engine_name()
            self.root.after(0, lambda: self._set_status(f"语音引擎就绪: {engine}"))
        except Exception as e:
            self.root.after(0, lambda: self._set_status(f"语音引擎加载失败: {e}"))

    # ==================== UI ====================
    def _build_ui(self):
        toolbar = ttkb.Frame(self.root, padding=(10, 8))
        toolbar.pack(fill=tk.X)

        ttkb.Label(toolbar, text="ClipVoice", font=("Microsoft YaHei", 14, "bold"),
                   bootstyle="primary").pack(side=tk.LEFT, padx=(0, 15))

        ttkb.Button(toolbar, text="粘贴文字", bootstyle="outline",
                    command=self._paste_text, width=10).pack(side=tk.LEFT, padx=3)
        ttkb.Button(toolbar, text="粘贴图片", bootstyle="outline",
                    command=self._paste_image, width=10).pack(side=tk.LEFT, padx=3)
        ttkb.Button(toolbar, text="删除", bootstyle="outline-danger",
                    command=self._delete_selected, width=8).pack(side=tk.LEFT, padx=3)

        search_frame = ttkb.Frame(toolbar)
        search_frame.pack(side=tk.LEFT, padx=10)
        ttkb.Label(search_frame, text="搜索:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refresh_history())
        ttkb.Entry(search_frame, textvariable=self.search_var, width=20).pack(side=tk.LEFT, padx=5)

        self.rec_btn = ttkb.Button(toolbar, text="  录音  ", bootstyle="danger",
                                   command=self._toggle_record, width=10)
        self.rec_btn.pack(side=tk.RIGHT, padx=5)

        main_paned = ttkb.Panedwindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))

        left_frame = ttkb.Frame(main_paned)
        list_header = ttkb.Frame(left_frame)
        list_header.pack(fill=tk.X)
        ttkb.Label(list_header, text="历史记录", font=("Microsoft YaHei", 10, "bold"),
                   bootstyle="secondary").pack(side=tk.LEFT, pady=5)
        self.count_label = ttkb.Label(list_header, text="0 条", bootstyle="secondary")
        self.count_label.pack(side=tk.RIGHT, pady=5)

        list_container = ttkb.Frame(left_frame)
        list_container.pack(fill=tk.BOTH, expand=True)
        self.history_list = tk.Listbox(
            list_container, font=("Microsoft YaHei", 10), activestyle="none",
            selectbackground="#4a90d9", selectforeground="white",
            bg="white", fg="#333", relief=tk.FLAT, bd=0,
            highlightthickness=1, highlightcolor="#4a90d9",
        )
        sb = ttkb.Scrollbar(list_container, orient=tk.VERTICAL, command=self.history_list.yview)
        self.history_list.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.history_list.pack(fill=tk.BOTH, expand=True)
        self.history_list.bind("<<ListboxSelect>>", self._on_select)
        self.history_list.bind("<Double-Button-1>", self._copy_selected)

        right_frame = ttkb.Frame(main_paned)
        preview_header = ttkb.Frame(right_frame)
        preview_header.pack(fill=tk.X)
        ttkb.Label(preview_header, text="内容预览", font=("Microsoft YaHei", 10, "bold"),
                   bootstyle="secondary").pack(side=tk.LEFT, pady=5)
        self.copy_btn = ttkb.Button(preview_header, text="复制到剪切板", bootstyle="success",
                                    command=self._copy_selected, width=14)
        self.copy_btn.pack(side=tk.RIGHT, pady=5)

        self.preview = tk.Text(
            right_frame, wrap=tk.WORD, font=("Microsoft YaHei", 11),
            state=tk.DISABLED, bg="#fafafa", fg="#333",
            relief=tk.FLAT, bd=0, highlightthickness=1,
            highlightcolor="#4a90d9", padx=12, pady=12,
        )
        self.preview.pack(fill=tk.BOTH, expand=True, pady=(0, 5))

        main_paned.add(left_frame, weight=1)
        main_paned.add(right_frame, weight=1)

        status_bar = ttkb.Frame(self.root, padding=(10, 5))
        status_bar.pack(fill=tk.X)
        self.status_var = tk.StringVar(value="正在初始化...")
        ttkb.Label(status_bar, textvariable=self.status_var,
                   font=("Microsoft YaHei", 9), bootstyle="secondary").pack(side=tk.LEFT)

        engine_info = f"语音引擎: {SpeechRecognizer.engine_name()}" if SpeechRecognizer.is_available() else "语音: 未安装"
        ttkb.Label(status_bar, text=engine_info,
                   font=("Microsoft YaHei", 9), bootstyle="secondary").pack(side=tk.RIGHT)

        self.id_to_item = {}
        self.item_images = {}

    def _set_status(self, text):
        self.status_var.set(text)

    # ==================== 剪切板轮询 ====================
    def _poll_clipboard(self):
        if not self._suppress_poll:
            changed, text, image, new_hash = ClipboardHelper.has_changed(
                self.last_clip_text, self.last_image_hash
            )
            if changed:
                self.last_clip_text = text or ""
                if image is not None:
                    buf = io.BytesIO()
                    image.save(buf, format="PNG")
                    self.db.save_clipboard("image", image_data=buf.getvalue())
                    self.last_image_hash = new_hash
                    self._refresh_history()
                    self._set_status(f"已捕获图片 ({image.size[0]}x{image.size[1]})")
                elif text and text.strip():
                    self.db.save_clipboard("text", text=text)
                    self._refresh_history()
                    self._set_status(f"已捕获文字 ({len(text)} 字)")
        self.root.after(1500, self._poll_clipboard)

    # ==================== 刷新列表 ====================
    def _refresh_history(self):
        self.history_list.delete(0, tk.END)
        self.id_to_item.clear()
        self.item_images.clear()
        keyword = self.search_var.get().strip()
        rows = self.db.search(keyword) if keyword else self.db.get_history()
        self.count_label.config(text=f"{len(rows)} 条")
        for idx, (rid, rtype, text, ts) in enumerate(rows):
            if rtype == "text":
                preview = (text or "")[:60].replace("\n", " ")
                display = f"  {preview}"
            else:
                display = "  [图片]"
            display += f"    {ts[:16]}"
            self.history_list.insert(tk.END, display)
            self.id_to_item[idx] = (rid, rtype)

    def _on_select(self, event):
        sel = self.history_list.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx not in self.id_to_item:
            return
        rid, rtype = self.id_to_item[idx]
        self.preview.configure(state=tk.NORMAL)
        self.preview.delete("1.0", tk.END)
        if rtype == "text":
            content = self.db.get_text_by_id(rid)
            self.preview.insert("1.0", content or "")
        else:
            data = self.db.get_image(rid)
            if data:
                img = Image.open(io.BytesIO(data))
                img.thumbnail((420, 420))
                photo = ImageTk.PhotoImage(img)
                self.item_images[rid] = photo
                self.preview.image_create(tk.END, image=photo)
            else:
                self.preview.insert("1.0", "[图片数据丢失]")
        self.preview.configure(state=tk.DISABLED)

    def _paste_text(self):
        text = ClipboardHelper.get_text()
        if text and text.strip():
            self.db.save_clipboard("text", text=text)
            self.last_clip_text = text
            self._refresh_history()
            self._set_status(f"已保存文字 ({len(text)} 字)")
        else:
            messagebox.showwarning("提示", "剪切板中没有文字内容")

    def _paste_image(self):
        image = ClipboardHelper.get_image()
        if image:
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            self.db.save_clipboard("image", image_data=buf.getvalue())
            self._refresh_history()
            self._set_status(f"已保存图片 ({image.size[0]}x{image.size[1]})")
        else:
            messagebox.showwarning("提示", "剪切板中没有图片")

    def _delete_selected(self):
        sel = self.history_list.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx in self.id_to_item:
            rid, _ = self.id_to_item[idx]
            self.db.delete_item(rid)
            self._refresh_history()
            self.preview.configure(state=tk.NORMAL)
            self.preview.delete("1.0", tk.END)
            self.preview.configure(state=tk.DISABLED)
            self._set_status("已删除")

    def _copy_selected(self, event=None):
        sel = self.history_list.curselection()
        if not sel:
            messagebox.showinfo("提示", "请先选择一条记录")
            return
        idx = sel[0]
        if idx not in self.id_to_item:
            return
        rid, rtype = self.id_to_item[idx]
        success = False
        if rtype == "text":
            content = self.db.get_text_by_id(rid)
            if content:
                success = ClipboardHelper.set_text(content)
                if success:
                    self.last_clip_text = content
                    self._suppress_poll = True
                    self.root.after(2000, self._resume_poll)
        else:
            data = self.db.get_image(rid)
            if data:
                img = Image.open(io.BytesIO(data))
                success = ClipboardHelper.set_image(img)
                if success:
                    self.last_image_hash = hash(img.copy().resize((64, 64)).tobytes())
                    self._suppress_poll = True
                    self.root.after(2000, self._resume_poll)
        if success:
            self._set_status("已复制到剪切板")
        else:
            self._set_status("复制失败")

    def _resume_poll(self):
        self._suppress_poll = False

    # ==================== 录音 ====================
    def _toggle_record(self):
        if not self.is_recording:
            if not SpeechRecognizer.is_available():
                messagebox.showwarning("提示", "未安装语音引擎，请先安装 funasr 或 sherpa-onnx")
                return
            self.is_recording = True
            self.rec_btn.configure(text="  停止  ", bootstyle="success")
            self._set_status("正在录音...")
            threading.Thread(target=self._record_thread, daemon=True).start()
        else:
            self.is_recording = False

    def _record_thread(self):
        self.recorder.start()
        start = time.time()
        while self.is_recording:
            time.sleep(0.1)
        audio = self.recorder.stop()
        duration = time.time() - start
        if audio is not None and len(audio) > 0:
            self.db.save_voice(audio, self.recorder.sample_rate, duration=duration)
            self.root.after(0, lambda: self._set_status(f"录音完成 ({duration:.1f}s)，识别中..."))
            threading.Thread(
                target=self._recognize_thread, args=(audio, self.recorder.sample_rate), daemon=True
            ).start()
        else:
            self.root.after(0, self._record_empty)

    def _recognize_thread(self, audio, sample_rate):
        try:
            text = SpeechRecognizer.recognize(audio, sample_rate)
            if text:
                self.db.save_clipboard("text", text=text)
                self.root.after(0, lambda: self._recognize_done(text))
            else:
                self.root.after(0, lambda: self._set_status("未识别到语音内容"))
        except Exception as e:
            self.root.after(0, lambda: self._set_status(f"识别出错: {e}"))

    def _recognize_done(self, text):
        self._set_status(f"识别成功: {text[:60]}")
        self._refresh_history()
        ClipboardHelper.set_text(text)
        self.last_clip_text = text
        self._suppress_poll = True
        self.root.after(2000, self._resume_poll)

    def _record_empty(self):
        self.rec_btn.configure(text="  录音  ", bootstyle="danger")
        self._set_status("录音为空，已取消")


# ==================== 入口 ====================
def main():
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = ttkb.Window(themename="litera")
    ClipboardManager(root)
    root.mainloop()


if __name__ == "__main__":
    main()
