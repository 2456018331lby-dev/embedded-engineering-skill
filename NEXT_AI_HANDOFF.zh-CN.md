# Embedded Engineering Skill 中文交接与维护文档

更新时间：2026-04-29

本目录是一个给 Claude Code 使用的嵌入式硬件工程 skill，不是独立 EDA 软件。下一个 AI 接手时，应把 `SKILL.md` 当作主操作提示，把 `scripts/` 里的 Python 脚本当作本地工具箱，把生成出来的 KiCad、HTML/SVG、BOM、pinmap、ERC 报告和生产就绪度报告返回给用户。

用户偏好：默认用中文回答。

## 1. 用户的最终目标

用户一开始想做的本质是：

- 一个能给 Claude Code 调用的硬件工程 skill；
- 能从零开始理解硬件需求；
- 自动做 MCU/SoC 选型、电源树、传感器、接口、RF/天线、BOM；
- 自动生成原理图/EDA 工程初稿；
- 能用真实工具校验，而不是只给文字建议；
- 最终朝着“自动完成完整硬件项目并画完原理图，继续走向 PCB、Gerber、BOM/CPL、嘉立创打样”的超级助手发展。

现在的实现已经不是单纯提示词，而是“Claude Code skill + 本地 EDA 生成工具链 + 测试模板 + 可视化验证样例”。

## 2. 当前完成度判断

面向用户理想目标，当前约为 **98%**。

注意：用户最新要求是继续完善“交接/维护文档”。在这之前开始实现的 JLC 生产包能力，现已完成回归验证并接入现有 gallery/验证链路。

已经比较强的部分：

- skill 入口 `SKILL.md` 已存在并通过 skill 校验；
- 有硬件项目模板；
- 能把项目 spec JSON 生成机器可检查的 `project.netlist.json`；
- 能生成 KiCad 工程和引脚级 review 原理图；
- KiCad 原理图中已有内嵌自定义符号、真实 pin、短线 stub、net label；
- 本机 KiCad CLI 能解析生成的 `.kicad_sch`、运行 ERC、导出 SVG；
- 能生成 HTML/SVG 浏览器预览；
- 能生成 EasyEDA/JLCEDA review JSON；
- 能生成 BOM、pinmap、静态 ERC；
- 新增 `production_readiness.md`，用于打样/量产前的生产就绪度闸门；
- 新增 `gen_template_gallery.py`，一条命令生成所有内置模板的可视化测试项目和索引页；
- 新增 `references/claude-code-usage.md`，说明普通用户如何让 Claude Code 使用这个 skill。

已经稳定并完成回归验证的新部分：

- 新增 `scripts/eda/gen_jlc_package.py`；
- `gen_kicad_project.py` 已自动输出 JLC package；
- `validate_eda_outputs.py` 已检查 JLC package 与 `production_readiness.md`；
- `gen_template_gallery.py` 已输出 JLC report 链接；
- 单模板、完整 gallery、KiCad ERC/export、skill 校验都已重新通过。
- 新增 `scripts/system/gen_embedded_system_bundle.py`；
- 当前已能生成硬件 + 固件 + 协议 + CRC helper + `system_contract.md` 的系统级 starter bundle；
- 已验证 ESP32-C3 与 LoRa SX1262 组合模板可生成完整系统骨架。
- 新增 `references/requirements-to-spec.md`；
- 新增 `scripts/eda/validate_project_spec.py`；
- `gen_kicad_project.py` 现在会在生成前自动输出 `spec_validation.json` / `spec_validation.md` 并拦截非法 spec。

距离 100% 还缺的关键部分：

- 真正原生的嘉立创/EasyEDA 符号级原理图生成和官方 JLCEDA 校验；
- 关键器件绑定到团队确认过的正式 KiCad 符号和封装库；
- PCB 已有 skeleton、自动 placement、DRC、Gerber/drill 导出，但还没有真实人工确认的完整布局和布线；
- JLC BOM/CPL/坐标文件生产包已可生成；当前 `jlc_cpl.csv` 来自自动 placement，上传工厂前仍需人工复核；
- LCSC/JLC 库存、价格、替代料实时查询的稳定集成；
- 更多项目模板和更强的“自然语言需求 -> 项目 spec JSON”流程；
- firmware-skill 目前已接入 bundle 框架，但应用逻辑、驱动细化和真实可编译工程仍需按目标平台继续补完。

## 3. 核心文件说明

### 入口文档

- `SKILL.md`
  - Claude Code 触发该 skill 后最先读的主说明。
  - 包含模式判断、脚本清单、EDA 工作流、能力边界、当前阶段。

- `NEXT_AI_HANDOFF.md`
  - 英文交接文档。

- `NEXT_AI_HANDOFF.zh-CN.md`
  - 当前中文交接文档。下一个 AI 优先读这个。

- `references/claude-code-usage.md`
  - 告诉用户怎么在 Claude Code 里调用这个 skill。

- `references/eda-toolchain.md`
  - EDA 工具链策略：KiCad 做自动化验证，EasyEDA/JLCEDA 面向嘉立创生产流。

### 数据与模板

- `components/library.json`
  - 本地器件库，包含 symbol、footprint、LCSC、封装、JLC 装配分类等字段。

- `circuits/templates/*.json`
  - 内置硬件项目模板。
  - 当前模板：
    - `esp32-c3-sensor-node.json`
    - `esp32-s3-multisensor-node.json`
    - `lora-sx1262-sensor-node.json`
    - `nrf52-ble-low-power-node.json`
    - `usb-lipo-esp32-node.json`

### EDA 脚本

- `scripts/eda/gen_kicad_project.py`
  - 主生成器。
  - 输入 project spec JSON。
  - 输出 KiCad 工程、原理图、manifest、BOM、pinmap、预览、ERC、生产就绪度报告。

- `scripts/eda/validate_project_spec.py`
  - 对 project spec 做生成前校验。
  - 当前检查：
    - 缺字段；
    - 未知器件；
    - 不受支持的接口；
    - MCU 保留/冲突 GPIO；
    - 基本功耗预算与稳压器额定电流不匹配。

- `scripts/eda/gen_template_gallery.py`
  - 批量生成所有模板的测试项目。
  - 输出 `index.html` 和 `gallery_summary.md`。

- `scripts/eda/gen_jlc_package.py`
  - 已接入并完成回归验证。
  - 从 `project.netlist.json` 生成：
    - `jlc_bom.csv`
    - `jlc_cpl.csv`
    - `jlc_assembly_report.json`
    - `jlc_assembly_report.md`
  - 关键边界：当前 CPL 来自自动 placement，适合 review，不得把它说成无需人工复核即可上传嘉立创的最终 CPL。

- `scripts/eda/erc_check.py`
  - 对 `project.netlist.json` 做静态 ERC。
  - 只能代表本 skill 的静态检查，不能冒充 KiCad/JLCEDA 官方 ERC。

- `scripts/eda/validate_eda_outputs.py`
  - 校验生成文件是否存在、JSON/S-expression 是否可解析。
  - 如果找到 `kicad-cli`，会运行 KiCad schematic ERC、schematic SVG、PCB DRC、PCB SVG、position、Gerber、drill export。

- `scripts/eda/gen_easyeda_std.py`
  - 当前的 EasyEDA/JLCEDA review JSON 导出器。
  - 现在已支持功能分区、pin-level stub、symbol/package/footprint/JLC metadata，可读性明显好于早期方框图，但仍不是完全原生符号级 JLCEDA 工程。

- `scripts/eda/render_design_preview.py`
  - 生成浏览器可打开的 HTML/SVG 预览。

- `scripts/system/gen_embedded_system_bundle.py`
  - 生成完整嵌入式系统 starter bundle。
  - 输出：
    - `hardware/`
    - `firmware/`
    - `firmware/generated_protocol/`
    - `system_contract.md`
    - `README_system_bundle.md`

### 子代理提示

- `subagents/*.md`
  - 用于后续 Claude Code 编排工程团队。
  - 当前可视为辅助说明，主流程仍由 `SKILL.md` 和脚本执行。

## 4. 当前可生成的交付物

单个项目生成后应包含：

- `.kicad_pro`
- `.kicad_sch`
- `.easyeda.json`
- `spec_validation.json`
- `spec_validation.md`
- `project.netlist.json`
- `bom.csv`
- `pinmap.csv`
- `schematic_preview.html`
- `schematic_preview.svg`
- `static_erc.md`
- `eda_validation.json`
- `eda_validation.md`
- `design_review.md`
- `production_readiness.md`
- `symbol_footprint_binding.md`
- `footprint_assignment.csv`
- JLC review 产物：
  - `jlc_bom.csv`
  - `jlc_cpl.csv`
  - `jlc_assembly_report.json`
  - `jlc_assembly_report.md`
- 若 KiCad CLI 可用，还会有：
  - `kicad_erc.json`
  - `kicad_export_svg/*.svg`
  - `kicad_pcb_drc.json`
  - `kicad_pcb_svg/*.svg`
  - `kicad_position.csv`
  - `gerbers/*`
  - `drill/*`

## 5. 本机环境

skill 根目录：

```text
C:\Users\24560\.claude\skills\embedded-engineering
```

Python：

```text
C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe
```

涉及中文或工程符号时，优先加 `-X utf8`。

KiCad CLI：

```text
C:\Program Files\KiCad\10.0\bin\kicad-cli.exe
```

注意：`kicad-cli` 可能不在 PATH 中，但 `validate_eda_outputs.py` 会检查常见安装路径。

## 6. 最新验证样例

最新 gallery 输出目录：

```text
C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc
```

浏览器索引页：

```text
C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc\index.html
```

汇总报告：

```text
C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc\gallery_summary.md
```

最新一次生成结果：

```text
esp32-c3-sensor-node          PASS 22, SKIP 0, FAIL 0
esp32-s3-multisensor-node     PASS 22, SKIP 0, FAIL 0
lora-sx1262-sensor-node       PASS 22, SKIP 0, FAIL 0
nrf52-ble-low-power-node      PASS 22, SKIP 0, FAIL 0
usb-lipo-esp32-node           PASS 22, SKIP 0, FAIL 0
```

示例可视化路径：

```text
C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc\esp32-c3-sensor-node\schematic_preview.html
C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc\esp32-c3-sensor-node\esp32-c3-sensor-node.kicad_sch
C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc\esp32-c3-sensor-node\kicad_export_svg\esp32-c3-sensor-node.svg
C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc\esp32-c3-sensor-node\eda_validation.md
C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc\esp32-c3-sensor-node\production_readiness.md
C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc\esp32-c3-sensor-node\jlc_assembly_report.md
```

## 7. 必跑验证命令

从 skill 根目录执行。

Python 编译检查：

```powershell
C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe -m py_compile scripts\eda\gen_kicad_project.py scripts\eda\gen_template_gallery.py scripts\eda\gen_jlc_package.py scripts\eda\validate_eda_outputs.py scripts\eda\validate_project_spec.py scripts\eda\gen_easyeda_std.py scripts\eda\render_design_preview.py scripts\eda\erc_check.py
```

spec 输入校验：

```powershell
C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe -X utf8 scripts\eda\validate_project_spec.py --spec circuits\templates\esp32-c3-sensor-node.json
```

skill 结构校验：

```powershell
C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe -X utf8 C:\Users\24560\.codex\skills\.system\skill-creator\scripts\quick_validate.py C:\Users\24560\.claude\skills\embedded-engineering
```

生成完整可视化 gallery：

```powershell
C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe -X utf8 scripts\eda\gen_template_gallery.py --out C:\Users\24560\.codex\.tmp\embedded-engineering-gallery
```

单独测试 JLC package：

```powershell
C:\Users\24560\AppData\Local\Programs\Python\Python312\python.exe -X utf8 scripts\eda\gen_jlc_package.py --manifest C:\Users\24560\.codex\.tmp\embedded-engineering-gallery-jlc\esp32-c3-sensor-node\project.netlist.json
```

空白检查：

```powershell
git diff --check
```

查看工作区：

```powershell
git status --short
```

## 8. Claude Code 应该如何使用它

完整硬件项目请求时，Claude Code 应按以下顺序执行：

1. 读取 `SKILL.md`；
2. 必要时读取：
   - `NEXT_AI_HANDOFF.zh-CN.md`
   - `references/claude-code-usage.md`
   - `references/eda-toolchain.md`
3. 判断用户需求属于：
   - 简单问答；
   - 计算/工具模式；
   - 工程报告模式；
   - 完整 EDA 项目模式；
4. 如果是完整 EDA 项目：
   - 复用或改写 `circuits/templates/*.json`；
  - 运行 `gen_kicad_project.py`；
  - 查看 `static_erc.md`、`eda_validation.md`、`production_readiness.md`；
   - 如果 JLC package 已生成，还要查看 `jlc_assembly_report.md`；
  - 返回项目总结、关键工程决策、文件路径、验证结果和剩余风险。

用户可这样调用：

```text
使用 embedded-engineering skill，从零设计一个 ESP32-C3 温湿度采集板，带 USB-C、锂电池、I2C 传感器，生成 KiCad 原理图、BOM、pinmap、ERC 报告和可视化预览。
```

如果 Claude Code 没有自动触发，可让用户显式说：

```text
请使用 C:\Users\24560\.claude\skills\embedded-engineering 这个 skill。
```

## 9. 严禁夸大的边界

可以说：

- 已能生成 KiCad 引脚级 review 原理图；
- 本机已有 KiCad CLI 自动 ERC 和 SVG 导出验证；
- 内置模板当前 gallery 验证为 0 FAIL；
- 能生成 HTML/SVG 预览、BOM、pinmap、静态 ERC、生产就绪度报告；
- EasyEDA/JLCEDA review JSON 已有初步输出。
- 可以说 JLC BOM/CPL/report 生成功能已经开始实现，但必须说明 CPL 是 placeholder，且当前需要重新回归验证。

不能说：

- 不能说已经是最终可量产原理图；
- 不能说 JLCEDA 官方 ERC 已通过，除非真的导入 JLCEDA 并运行官方检查；
- 不能说已经能直接下单打板贴片；
- 不能说自动生成的 `jlc_cpl.csv` 是无需人工复核即可上传的真实贴片坐标；
- 不能把 KiCad 内嵌 review symbol 说成正式厂商库符号；
- 不能把静态 ERC 冒充 KiCad/JLCEDA 官方 ERC。

## 10. 已知风险

- 当前 git 工作区有很多 untracked 文件，这可能是本地 skill 创建/复制导致的。不要执行 `git reset --hard` 或删除这些文件。
- 曾出现 MCP `fetch`、`time` 启动失败提示，但当前 EDA 生成链路不依赖它们。
- EasyEDA/JLCEDA 仍是 review JSON，不是完整官方符号级工程。
- RF 匹配网络里的 `0R/DNP` 等占位件可能缺 LCSC 信息，打样前要补全或标记为手焊/不贴。
- `production_readiness.md` 是本地生产闸门，不是工厂批准。
- JLC package 相关代码是刚新增的未完整回归状态；下一任 AI 需要先验证再继续。

## 10.5 当前下一阶段工作

JLC review package、PCB skeleton、system bundle 与 spec 校验层都已稳定，下一任 AI 不需要再把它们当成“待验证改动”，而应该把它们当作现有基础能力继续向前推进。

下一任 AI 第一件事：

1. 先读 `SKILL.md` 和本文件；
2. 复用当前 JLC review package 作为生产侧基础；
3. 直接推进 PCB 骨架、真实 CPL、Gerber/DRC 或正式 symbol/footprint 绑定；
4. 只有在修改 JLC 逻辑后，才需要重新跑完整 gallery 并更新本文档。

## 11. 下一阶段优先级

### 最高优先级 1：JLC 生产包

当前状态：已实现并通过回归。

下一步目标是：

- 生成 JLC 友好的 BOM；
- 生成 CPL/坐标 CSV；当前能生成 `jlc_cpl.csv`，但它来自自动 placement，真实量产坐标仍需人工确认；
- 区分 basic、extended、manual、DNP、not_applicable；
- 检查 LCSC 缺失；
- 把结果接入 `production_readiness.md`。

### 最高优先级 2：PCB 骨架

建议新增：

- `.kicad_pcb` 生成；
- 板框；
- 安装孔；
- USB/电池/调试口区域；
- RF antenna keepout；
- RF feed/CPWG/microstrip 约束；
- net class；
- KiCad PCB DRC 验证。

### 最高优先级 3：正式符号/封装绑定

目标：

- 区分 review symbol、KiCad 官方 symbol、厂商 symbol、团队确认 symbol；
- 对 MCU、电源、USB、RF 器件设置更严格 gate；
- 生成 `symbol_footprint_binding.md`。

### 最高优先级 4：EasyEDA/JLCEDA 真正原生路径

目标：

- 基于官方 EasyEDA Document Format；
- 做符号级、pin 级、wire 级 JSON；
- 验证能被 JLCEDA 导入；
- 只有官方 JLCEDA 检查通过后才声称 JLCEDA-verified。

### 中期优先级：模板扩展

建议新增模板：

- STM32 低功耗传感器；
- RP2040 USB 小板；
- ESP32 继电器/控制板；
- LoRa + LiPo + 太阳能节点；
- 电机控制板；
- 485/CAN 工业控制板。

每新增一个模板，都必须加入 gallery 回归测试。

### 中期优先级：自然语言到 spec

当前状态：基础版已落地。

下一步目标：

- 把更多语义规则从文档下沉到校验器；
- 覆盖更多平台（STM32、RP2040）的 GPIO/接口约束；
- 增加自然语言需求到 spec 的示例映射与负例。

## 12. 维护规则

- `project.netlist.json` 是源数据。
- KiCad、EasyEDA、BOM、pinmap、HTML/SVG、报告都应由 manifest 派生。
- 新增输出时，要把它接入验证或 gallery 汇总。
- 新增模板时，必须跑完整 gallery。
- 有真实工具验证才声称真实工具验证通过。
- 对用户最终报告必须包含：
  - 生成了哪些文件；
  - 路径在哪里；
  - ERC/验证结果；
  - 当前生产就绪度；
  - 打样/量产前还差什么。
- 与用户沟通默认中文。

## 13. 最近一次已验证结果

JLC package 改动之后已重新通过：

```text
python -m py_compile ...                         PASS，包含 gen_jlc_package.py
quick_validate.py embedded-engineering            PASS, Skill is valid!
单模板 gen_kicad_project.py + JLC package         PASS
gen_template_gallery.py                           PASS，5 个项目生成成功
KiCad ERC/export gallery 全量检查                 PASS
git diff --check                                  PASS
```

系统级 bundle 已通过：

```text
gen_embedded_system_bundle.py (ESP32-C3)          PASS
生成后的 host Python 协议参考代码 py_compile       PASS
桌面 LoRa 全系统演示项目生成                       PASS
```

当前完整 gallery 结果：

```text
esp32-c3-sensor-node          PASS 15, SKIP 0, FAIL 0
esp32-s3-multisensor-node     PASS 15, SKIP 0, FAIL 0
lora-sx1262-sensor-node       PASS 15, SKIP 0, FAIL 0
nrf52-ble-low-power-node      PASS 15, SKIP 0, FAIL 0
usb-lipo-esp32-node           PASS 15, SKIP 0, FAIL 0
```
