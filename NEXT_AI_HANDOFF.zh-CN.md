# Embedded Engineering Skill 中文交接文档

更新时间：2026-04-29

这是一个 Claude Code 嵌入式硬件 EDA 自动化 skill。
主参考文件：`SKILL.md` — 接手时先读它。
用户偏好：默认中文回答。

## 已能正常工作的功能

- 项目 spec JSON -> KiCad 工程 + 引脚级原理图生成 (`gen_kicad_project.py`)
- 本机 KiCad CLI 可解析、ERC、导出 SVG
- 基于 `project.netlist.json` 的静态 ERC（自定义，非官方 KiCad ERC）
- HTML/SVG 浏览器预览 (`render_design_preview.py`)
- EasyEDA/JLCEDA review JSON 导出 (`gen_easyeda_std.py`)
- BOM、pinmap、生产就绪度报告生成
- JLC 装配包：`jlc_bom.csv`、`jlc_cpl.csv`、装配报告
- 生成前 spec 校验 (`validate_project_spec.py`)
- 系统级 bundle：硬件 + 固件骨架 + 协议 + system_contract
- Gallery 回归：5 个模板全部通过（每模板 22 项检查，0 FAIL）

## 不工作 / 已知限制

- `jlc_cpl.csv` 来自自动 placement — 上传工厂前必须人工复核
- EasyEDA 输出是 review JSON，不是原生 JLCEDA 符号级原理图
- 无 LCSC/JLC 库存、价格、替代料实时查询集成
- 静态 ERC 是自定义检查，不能替代 KiCad/JLCEDA 官方 ERC
- PCB 已有 skeleton，但无真实人工布局/布线
- RF 占位件 (0R/DNP) 的 LCSC 信息可能不完整
- `production_readiness.md` 是本地闸门，不是工厂批准

## 如何扩展

### 新增模板
1. 创建 `circuits/templates/<name>.json`，参考已有模板格式
2. 运行 `gen_kicad_project.py` — 修复 spec 校验错误
3. 运行 `gen_template_gallery.py`，确认 0 FAIL
4. `py_compile` 所有 eda 脚本

### 修改生成器逻辑
1. 编辑 `scripts/eda/` 中对应脚本
2. `py_compile` 改动文件
3. 重新生成完整 gallery，确认 0 FAIL
4. 若 KiCad CLI 可用，验证 ERC/export 仍通过

### 新增 EDA 输出类型
1. 在 `gen_kicad_project.py` 中添加生成逻辑
2. 在 `validate_eda_outputs.py` 中添加校验
3. 在 `gen_template_gallery.py` 中添加汇总链接
4. 重新生成 gallery，确认 0 FAIL

## 关键路径

```
Skill 根目录：C:\Users\24560\.claude\skills\embedded-engineering
Python：       C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe
KiCad CLI：    C:\Program Files\KiCad\10.0\bin\kicad-cli.exe
Gallery 输出： C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc\
```

## 验证命令

```powershell
# 编译检查（从 skill 根目录执行）
python -m py_compile scripts\eda\gen_kicad_project.py scripts\eda\gen_template_gallery.py scripts\eda\gen_jlc_package.py scripts\eda\validate_eda_outputs.py scripts\eda\validate_project_spec.py scripts\eda\gen_easyeda_std.py scripts\eda\render_design_preview.py scripts\eda\erc_check.py

# 校验单个 spec
python -X utf8 scripts\eda\validate_project_spec.py --spec circuits\templates\esp32-c3-sensor-node.json

# Skill 结构校验
python -X utf8 C:\Users\24560\.codex\skills\.system\skill-creator\scripts\quick_validate.py C:\Users\24560\.claude\skills\embedded-engineering

# 完整 gallery
python -X utf8 scripts\eda\gen_template_gallery.py --out C:\Users\24560\.codex\.tmp\embedded-engineering-gallery

# 空白检查
git diff --check
```

## 下一阶段工作（按优先级）

1. JLC 生产包增强：改进 CPL 生成、LCSC 完整性检查
2. PCB 骨架：`.kicad_pcb` 生成，含板框、安装孔、keepout 区域
3. 符号/封装绑定：区分 review 符号 vs 官方 vs 厂商确认符号
4. EasyEDA 原生路径：符号级 JLCEDA 输出，验证可导入
5. 更多模板：STM32、RP2040、电机控制、RS-485/CAN 工业板

## 维护规则

- `project.netlist.json` 是源数据 — 所有输出都从它派生
- 新增输出必须接入 `validate_eda_outputs.py` 或 gallery 汇总
- 每个新模板必须通过：py_compile + gallery + 静态 ERC（0 FAIL）
- 不夸大：只说经过工具验证的结果
