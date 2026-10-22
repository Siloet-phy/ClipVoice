<p align="center">
  <h1 align="center">ClipVoice</h1>
  <p align="center">
    <strong>智能剪切板管理器</strong> — 文字/图片/语音，一站搞定
  </p>
  <p align="center">
    <img src="https://img.shields.io/badge/python-3.8+-blue.svg" alt="Python">
    <img src="https://img.shields.io/badge/platform-Windows-lightgrey.svg" alt="Platform">
    <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License">
    <img src="https://img.shields.io/badge/version-1.0.0-orange.svg" alt="Version">
  </p>
</p>

---

ClipVoice 是一款 Windows 桌面端的智能剪切板管理器，支持文字和图片的自动捕获、历史记录持久化、关键词搜索，以及**本地离线语音录入与转写**。

## 功能特性

| 功能 | 说明 |
|------|------|
| 文字/图片捕获 | 自动监听系统剪切板，复制即记录 |
| 历史持久化 | SQLite 本地存储，关闭再打开不丢失 |
| 关键词搜索 | 实时过滤历史记录 |
| 一键回写 | 选中历史记录，一键复制回系统剪切板 |
| 语音录入 | 麦克风录音，WAV 文件自动保存 |
| 语音转文字 | 本地离线 ASR，支持 FunASR / SenseVoice |
| 现代 UI | ttkbootstrap 扁平主题，告别 tkinter 土味 |

## 快速开始

### 环境要求

- Windows 10/11
- Python 3.8+

### 安装

```bash
# 1. 克隆仓库
git clone https://github.com/YOUR_USERNAME/ClipVoice.git
cd ClipVoice

# 2. 安装依赖
pip install -r requirements.txt

# 3. （可选）安装语音引擎
pip install funasr          # FunASR（中文最准）
# 或
pip install sherpa-onnx     # sherpa-onnx SenseVoice（轻量多语言）

# 4. 启动
python src/clipboard_manager.py
```

### Windows 一键启动

双击 `run.bat`，自动检测并安装依赖。

## 语音引擎

ClipVoice 支持两种本地离线语音识别引擎，启动时自动检测：

| 引擎 | 安装方式 | 中文准确率 | 模型大小 | 特点 |
|------|----------|-----------|---------|------|
| **FunASR Paraformer-zh** | `pip install funasr` | 最高 | ~1.1GB | 阿里达摩院出品，中文首选 |
| **sherpa-onnx SenseVoice** | `pip install sherpa-onnx` | 高 | ~228MB | 轻量级，支持中英日韩粤 |

无需联网，所有语音识别均在本地完成。

## 项目结构

```
ClipVoice/
├── src/
│   └── clipboard_manager.py   # 主程序
├── data/                       # 运行时数据（自动创建）
│   ├── clipboard.db            # SQLite 数据库
│   └── recordings/             # 语音录音文件
├── requirements.txt
├── run.bat                     # Windows 启动脚本
├── LICENSE
└── README.md
```

## 技术栈

- **UI**: [ttkbootstrap](https://github.com/israel-dryer/ttkbootstrap) — 现代化 tkinter 主题
- **剪切板**: `pywin32` / `win32clipboard` — Windows 原生 API
- **数据库**: SQLite3 — 零配置本地存储
- **语音识别**: [FunASR](https://github.com/modelscope/FunASR) / [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx)
- **音频**: `sounddevice` + `soundfile`

## 使用方式

1. **自动捕获**: 启动后自动监听剪切板，复制任何文字/图片都会自动记录
2. **手动粘贴**: 点击「粘贴文字」或「粘贴图片」手动保存当前剪切板内容
3. **搜索**: 在搜索框输入关键词，实时过滤历史记录
4. **复制回写**: 选中历史记录 → 点击「复制到剪切板」或双击条目
5. **语音录入**: 点击「录音」按钮 → 说话 → 点击停止 → 自动识别并写入剪切板

## License

[MIT License](LICENSE)
