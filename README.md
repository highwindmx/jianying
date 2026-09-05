# 剪影 (jianying)

> 屏幕截图 + 背景美化桌面工具（Windows）。区域 / 全屏截图 → 标注 → 圆角 / 阴影 / 渐变 / 纯色 / 透明背景 → 复制 / 保存 / 贴图；内置区域屏幕录像（MP4）与滚动截图（长图拼接）。 当前版本 **v0.1.0**。

## 功能特性

-   **截图**：区域框选、全屏、滚动长图拼接
-   **框选工具条**：复制剪贴板 / 保存到本地 / 滚动截图 / 屏幕录像 / 截图编辑 / 取消截图（可拖动）
-   **背景美化**（核心卖点）：32 款内置背景（透明 / 纯色 / 渐变），可调留白、圆角、右下阴影、画面比例（含自定义）；用户可放 JSON 扩展
-   **标注**：画笔、箭头（尖头 / 圆头 / 无头）、矩形、椭圆、正多边形、自由多边形、文字（内联编辑）、马赛克
-   **编辑器画布缩放**：25%–800%，所见即所得
-   **取色**：框选时放大镜显示颜色，`C` / `Shift+C` 复制 HEX / RGB 到剪贴板
-   **屏幕录像**：区域连帧录制（含录制范围加粗红框提示），编码器自动回退
-   **贴图**：把上一张截图钉在桌面最前
-   **托盘常驻** + 全局热键

## 安装与运行

### 方式 A：直接运行（推荐普通用户）

获取发布包里的 `jianying.exe`（见下方「构建可执行文件」），双击即可，无需 Python 环境。 首次运行托盘出现彩虹「剪」字图标，按热键开始截图。

### 方式 B：源码运行（开发）

```powershell
cd D:\Share\Scripts\Explore\jianying
uv sync                 # 创建 .venv 并安装依赖（生成 uv.lock）
uv run jianying         # 启动，托盘常驻
```

## 构建可执行文件（Windows）

使用 PyInstaller，构建脚本在 `tools/build_exe.py`：

```powershell
uv sync                          # 确保已装 pyinstaller（已列入 dev 依赖）
uv run python tools/build_exe.py            # onedir：dist/jianying/jianying.exe（启动快，推荐）
uv run python tools/build_exe.py --onefile  # 单文件：dist/jianying.exe（分发方便，启动略慢）
```

-   `--windowed`：GUI 应用，不弹黑框控制台
-   背景模板目录 `assets/` 会一并打进 exe，用户也可在 `jianying.exe` 同级放 `assets/` 覆盖内置模板
-   需要调试时，把 `tools/build_exe.py` 里的 `--windowed` 改为 `--console` 重新打包，即可看到控制台输出

打包后冒烟自检：

```powershell
dist\jianying\jianying.exe --version   # 打印 jianying 0.1.0，退出码 0 表示依赖收集完整
```

## 热键

热键

功能

Ctrl+Shift+A

区域截图

Ctrl+Shift+F

全屏截图

Ctrl+Shift+S

贴图上一张

Ctrl+Shift+D

滚动截图

框选时 Tab

吸附到窗口边界

方向键 / Shift+方向键

选区微调 1px / 10px

框选时 C / Shift+C

复制鼠标处颜色 `#RRGGBB` / `rgb(r,g,b)` 到剪贴板

Esc

取消

### 编辑器内

快捷键

功能

Ctrl+Z / Ctrl+Y

撤销 / 重做（逐步）

Ctrl+= / Ctrl+- / Ctrl+0

画布放大 / 缩小 / 复位 100%

文字工具 Enter / Esc / Shift+Enter

确认 / 取消 / 换行

## 配置

复制 `.env.example` 为 `.env` 按需修改（热键、保存目录、`RECORD_FPS` 录像帧率、OCR token 等）。 未提供 `.env` 时使用内置默认值。

## 自定义背景模板

在 `assets/templates/` 放 JSON，格式同内置模板（`type`：`none` / `transparent` / `solid` / `gradient`）：

```json
{"name": "我的背景", "type": "gradient", "colors": ["#2193b0", "#6dd5ed"],
 "angle": 135, "padding": 48, "radius": 16, "shadow": {"blur": 40, "opacity": 110, "offset_y": 14}}
```

-   **源码运行**：放在项目 `assets/templates/`
-   **打包运行**：放在 `jianying.exe` 同级 `assets/templates/`（优先级高于内置）

## 冒烟测试（不开 GUI）

```powershell
uv run python -m jianying --test-grab   # 只测 mss 截屏并保存 test_grab.png
uv run python -m jianying --version      # 打印版本
```

## 目录结构

```
jianying/
├── jianying/            # 源码包
│   ├── __main__.py      # 入口（python -m jianying）
│   ├── app.py           # 总装：托盘 + 热键 + 流程编排
│   ├── capture/         # 截图 / 滚动 / 录像 / 区域框选
│   ├── editor/          # 编辑器：标注 + 美化 + 背景模板
│   ├── config.py        # 路径 / 热键 / OCR 配置
│   └── icon.py          # 运行时生成彩虹「剪」字图标
├── assets/              # 图标 + 背景模板目录（打包内置）
├── tests/               # 回归测试脚本
├── tools/               # 构建脚本（build_exe.py）
├── pyproject.toml
└── LICENSE              # MIT
```

## 已知限制（v0.1.0）

-   **仅 Windows**（热键 / 托盘 / 截屏均为 Windows 实现）
-   DPI 策略：全局禁用 Qt 缩放（1:1 物理像素）保证截图坐标链零误差；高缩放屏上 UI 字号偏小属预期
-   滚动截图为实验功能，仅适配常见网页 / 文档滚动
-   屏幕录像**不含音频**；编码器按 `mp4v → avc1 → XVID(avi)` 依次回退，帧率由 `RECORD_FPS` 控制
-   录像进行中会在录制区域显示加粗红框（透明、鼠标穿透，便于看清范围，也会落在录像边缘，属预期）

## 许可证

[MIT](./LICENSE) © 2026 Highwindmx@126.com

Powered by Workbuddy

Idea from https://xnapper.com/zh-CN