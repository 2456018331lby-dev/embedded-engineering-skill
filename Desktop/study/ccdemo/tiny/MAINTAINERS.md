     1|# Tiny Companion Robot 维护手册
     2|
     3|> 给后续维护者/AI看的项目入口文档。先看本文件，再改代码。
     4|
     5|## 1. 这个项目是干什么的
     6|
     7|本项目是一个“抽象小陪伴机器人”的双 MCU 原型工程：
     8|
     9|- STM32H743：感知层，负责音频采集、轻量特征提取、触摸检测、LED 表情矩阵、舵机动作。
    10|- ESP32-S3：决策层，负责情感状态机、三种人格（曼波/哈基米/牢大）、用户记忆、音频播放、WiFi/MQTT 可选上报。
    11|- 双方通过 UART 921600bps 通信。
    12|- `ml/` 用于训练/导出语音情感识别模型，目前固件主线还没有真正接入 TFLite Micro，只是保留 ML 管线。
    13|
    14|当前更像“可继续联调的嵌入式原型”，不是量产级固件。
    15|
    16|## 2. 当前真实状态（重要）
    17|
    18|### 已有模块
    19|
    20|- `stm32/Core/Src/audio_capture.c`：I2S + DMA 采集 INMP441。
    21|- `stm32/Core/Src/feature_extract.c`：RMS、ZCR、13 个 Goertzel 频带，输出 16 字节特征。
    22|- `stm32/Core/Src/touch_sensor.c`：单路 TTP223 触摸，短按/长按/双击。
    23|- `stm32/Core/Src/led_matrix.c`：WS2812B 8x8 表情矩阵。
    24|- `stm32/Core/Src/servo_ctrl.c`：双 SG90 舵机预设动作。
    25|- `stm32/Core/Src/protocol.c`：STM32 端 UART v0 协议。
    26|- `esp32/src/protocol.cpp`：ESP32 端 UART v0 协议，已按 STM32 当前协议对齐。
    27|- `esp32/src/emotion_engine.cpp`：Russell valence/arousal 情感状态机。
    28|- `esp32/src/personality.cpp`：三人格行为/语音/表情/动作决策。
    29|- `esp32/src/memory_system.cpp`：NVS 记忆和成就系统。
    30|- `esp32/src/audio_player.cpp`：SPIFFS WAV 播放到 MAX98357A。
    31|- `ml/*.py`：训练、导出、推理测试脚本。
    32|- `tools/generate_audio.py`：生成三人格预录音频。
    33|
    34|### 文档与代码差异
    35|
    36|`docs/protocol.md` 描述的是计划中的 v1 协议：
    37|
    38|```text
    39|[0xAA][LEN][TYPE][CMD][PAYLOAD][CRC]
    40|CRC poly=0x07，payload max 64，无 footer
    41|```
    42|
    43|当前代码实际使用 v0 协议：
    44|
    45|```text
    46|[0xAA][Length][Type][Payload...][CRC8][0x55]
    47|Length = 整帧长度 = 5 + payload_len
    48|Type 直接承担消息类型/命令号
    49|CRC8 = crc8(Length + Type + Payload)，poly=0x07
    50|```
    51|
    52|短期维护以“当前 v0 协议能联调”为优先。等硬件通信跑通后，再决定是否迁移到 `docs/protocol.md` 的 v1。
    53|
    54|## 3. 目录结构
    55|
    56|```text
    57|tiny/
    58|├── README.md                  # 面向用户的项目简介（部分内容仍偏规划）
    59|├── MAINTAINERS.md             # 本维护手册
    60|├── docs/
    61|│   ├── architecture.md         # 架构设计，偏目标态
    62|│   ├── hardware.md             # 硬件接线/BOM
    63|│   └── protocol.md             # v1 协议草案，不等同当前代码
    64|├── stm32/                      # STM32H743 感知层固件
    65|│   ├── Core/Inc/               # STM32 头文件
    66|│   ├── Core/Src/               # STM32 源文件
    67|│   ├── Drivers/                # HAL/CMSIS 预期位置；当前可能缺失
    68|│   ├── Startup/                # 启动汇编
    69|│   └── Makefile
    70|├── esp32/                      # ESP32-S3 决策层固件（PlatformIO/Arduino）
    71|│   ├── include/config.h        # ESP32 全局配置/ID映射
    72|│   ├── src/                    # ESP32 源码
    73|│   ├── data/                   # SPIFFS 音频资源预期目录
    74|│   └── platformio.ini
    75|├── ml/                         # 机器学习训练/导出/测试
    76|└── tools/                      # 烧录和音频生成工具
    77|```
    78|
    79|## 4. 当前 UART v0 协议速查
    80|
    81|物理层：UART 921600, 8N1, 3.3V, TX/RX 交叉，共地。
    82|
    83|帧格式：
    84|
    85|```text
    86|Offset  Field    Size
    87|0       Header   1 byte, fixed 0xAA
    88|1       Length   1 byte, total frame length, 5 + payload_len
    89|2       Type     1 byte
    90|3..N    Payload  0..250 bytes
    91|N+1     CRC8     1 byte, poly 0x07 over [Length, Type, Payload]
    92|N+2     Footer   1 byte, fixed 0x55
    93|```
    94|
    95|STM32 -> ESP32：
    96|
    97|| Type | 名称 | Payload |
    98||---|---|---|
    99|| 0x01 | AUDIO_FEATURE | 16 bytes: `[rms,zcr,band0..band12,reserved]`，uint8 |
   100|| 0x02 | TOUCH_EVENT | 1 byte: 0 none, 1 short, 2 long, 3 double |
   101|| 0x03 | BATTERY_VOLTAGE | 2 bytes little-endian；当前 STM32 还未真正上报 ADC |
   102|
   103|ESP32 -> STM32：
   104|
   105|| Type | 名称 | Payload |
   106||---|---|---|
   107|| 0x01 | EXPRESSION | 1 byte 表情 ID |
   108|| 0x02 | ACTION | 1 byte 舵机动作 ID |
   109|| 0x03 | VOLUME | 1 byte；STM32 当前忽略 |
   110|| 0x04 | SLEEP | 1 byte flag |
   111|
   112|表情 ID 当前按 STM32 `led_matrix.h`：
   113|
   114|| ID | STM32 名称 | ESP32 语义映射 |
   115||---|---|---|
   116|| 0 | NEUTRAL | neutral/calm |
   117|| 1 | SMILE | happy |
   118|| 2 | LAUGH | 暂少用 |
   119|| 3 | CONFUSED | sad/confused 临时映射 |
   120|| 4 | THINKING | 暂少用 |
   121|| 5 | SLEEPING | sleepy |
   122|| 6 | ANGRY | angry |
   123|| 7 | SURPRISED | excited/achievement |
   124|
   125|动作 ID 当前按 STM32 `servo_ctrl.h`：
   126|
   127|| ID | 动作 |
   128||---|---|
   129|| 0 | none |
   130|| 1 | nod |
   131|| 2 | shake |
   132|| 3 | look around |
   133|| 4 | tilt head |
   134|
   135|## 5. 开发/验证命令
   136|
   137|### 5.1 Python 语法和轻量检查
   138|
   139|```bash
   140|cd /mnt/c/Users/24560/Desktop/study/ccdemo/tiny
   141|python3 -m py_compile ml/*.py tools/*.py
   142|bash -n tools/flash_all.sh
   143|python3 tools/generate_audio.py --dry-run --engine tone --personality manbo
   144|```
   145|
   146|### 5.2 ML 环境
   147|
   148|建议用 Python 3.10/3.11 虚拟环境，不建议直接用当前系统 Python 3.12。
   149|
   150|```bash
   151|cd ml
   152|python -m venv .venv
   153|source .venv/bin/activate
   154|pip install -r requirements.txt
   155|python generate_test_data.py
   156|python train_emotion.py --use_synthetic
   157|python export_tflite.py
   158|python test_model.py --audio datasets/synthetic/happy/happy_000.wav
   159|```
   160|
   161|### 5.3 ESP32 编译/烧录
   162|
   163|```bash
   164|cd esp32
   165|pio run -e esp32s3
   166|pio run -e esp32s3 -t upload
   167|pio device monitor
   168|```
   169|
   170|注意：当前 `platformio.ini` 是 `espressif32@6.9.0`，但 `audio_player.cpp` 使用 ESP-IDF 5.x 风格 `driver/i2s_std.h`。如果编译失败，优先二选一：
   171|
   172|1. 升级 PlatformIO/Arduino core 到支持 Arduino-ESP32 3.x/IDF5 的版本，并同步修 `esp_task_wdt_init` API。
   173|2. 保持 espressif32@6.9.0，把音频 I2S 改回旧 API：`i2s_driver_install / i2s_set_pin / i2s_write`。
   174|
   175|### 5.4 STM32 编译/烧录
   176|
   177|```bash
   178|cd stm32
   179|make clean
   180|make -j$(nproc)
   181|make flash
   182|```
   183|
   184|注意：当前环境里 `arm-none-eabi-gcc` 不可用，而且 `Drivers/` 可能缺 HAL/CMSIS 源文件。若要真正编译，先补齐：
   185|
   186|- ARM GNU Toolchain
   187|- STM32H7 HAL/CMSIS Drivers
   188|- `stm32h7xx_hal_conf.h`
   189|- Makefile 中 HAL 源文件列表
   190|
   191|## 6. 已知问题/下一步优先级
   192|
   193|### 上板前预备工作清单（硬件前必须完成）
   194|
   195|1. 先确认文档和代码基线一致：当前实际通信协议是 v0，不是 `docs/protocol.md` 的 v1；触摸输入按单路 TTP223 处理，不按旧规划的多路触摸准备。
   196|2. 先分别完成双端独立可编译：
   197|   - ESP32 固定在 `espressif32@6.9.0` / Arduino 2.x / IDF 4.4，确认 `audio_player.cpp` 不再混入 IDF 5.x API。
   198|   - STM32 先补齐 HAL/CMSIS、`stm32h7xx_hal_conf.h`、Makefile 源文件和 ARM GNU Toolchain，至少保证能完整链接。
   199|3. 先完成离线一致性验证，再碰硬件：
   200|   - `python3 tests/test_protocol_v0.py`
   201|   - `python3 scripts/check_consistency.py`
   202|4. 先核对关键接线和电平：
   203|   - UART 只用 STM32 PA9/PA10 ↔ ESP32 GPIO8/GPIO4，TX/RX 交叉，3.3V 电平，共地。
   204|   - INMP441 只接 STM32 I2S2；MAX98357A 只接 ESP32 I2S；不要接反。
   205|   - WS2812B→PA8，触摸→PC0，舵机→PB6/PB7。
   206|5. 先确认供电设计，不要直接靠板载弱供电拖全系统：舵机、功放、LED 需要稳定 5V 供电；逻辑侧保持 3.3V；所有模块必须共地，优先排查掉压、地弹和舵机干扰。
   207|6. 先规划最小化联调路径：先双板串口，再 LED/舵机，再麦克风，再音频播放，最后再整机联调；不要第一次上电就全外设同时接入。
   208|7. 先准备观测手段：ESP32 串口日志、STM32 调试接口/串口、万用表/电流观察；没有这些就不要直接开始整机上板排错。
   209|
   210|P0：硬件联调前必须解决
   211|
   212|1. 确认 ESP32 是否能编译；若卡在 I2S API，先统一 Arduino/IDF 版本。
   213|2. 补齐 STM32 HAL/CMSIS 驱动和 Makefile 源文件，确保能完整链接。
   214|3. 上板抓 UART，确认 v0 协议收发：STM32 音频特征/触摸 -> ESP32；ESP32 表情/动作 -> STM32。
   215|4. 确认 LED `LED_SetExpression()` 能立即刷新；当前已改为直接启动一次 DMA。
   216|5. 确认 IWDG reload 合法；当前已从 5000 改为 4095，Error_Handler 不再喂狗。
   217|
   218|P1：功能一致性
   219|
   220|1. 电池 ADC 读取仍是占位，需实现真实 ADC 初始化和上报。
   221|2. STM32 睡眠/STOP 恢复流程未充分验证，联调前可先禁用或标记实验。
   222|3. ESP32 `Memory_RecordInteraction(..., voiceIndex)` 仍传 0，语音成就不可完整达成。
   223|4. MQTT callback 只打印，不解析远程命令。
   224|5. 触摸只有单路 PC0；文档里曾写 3 路，需按实际硬件统一。
   225|
   226|P2：架构升级
   227|
   228|1. 决定是否迁移到 `docs/protocol.md` v1 协议。
   229|2. 决定情绪识别在 STM32 端跑 TFLite Micro，还是 ESP32 根据低级特征决策。
   230|3. 如果接入 ML 模型，需要把 `ml/export_tflite.py` 生成的 `emotion_model.h` 接入固件，并补推理模块。
   231|4. 如果保留轻量特征路线，应把 README/architecture/protocol 改成真实实现描述，避免误导。
   232|
   233|## 7. 最近维护变更记录
   234|
   235|2026-05-03（续）：
   236|
   237|- **audio_player.cpp 修复**：ESP-IDF 5.x `i2s_channel_*` API → IDF 4.4 legacy `i2s_driver_install / i2s_write`。解决 platformio.ini `espressif32@6.9.0` (Arduino 2.x / IDF 4.4) 编译必挂问题。
   238|- **config.h 表情 ID 注释**：补充 EXPR_SAD/EXPR_CONFUSED 同值(=3)映射说明，ESP32→STM32 映射表完整文档化。
   239|- **tests/test_protocol_v0.py**：从 8 个测试扩充到 22 个。新增 TestEdgeCases(边界)、TestValueMapping(数值映射)、TestCRC(校验向量)。
   240|- **scripts/check_consistency.py**：新增离线一致性检查脚本，自动对比 ESP32/STM32 消息类型、表情ID、动作ID、触摸事件、协议常量。
   241|- **AGENTS.md**：新增面向 AI 的完整维护指南（目录结构、约定、踩坑清单、验证方法）。
   242|- **docs/protocol.md**：顶部加 ⚠️ 警告，标注为 v1 计划协议而非 v0 实际协议。
   243|
   244|2026-05-03：
   245|
   246|- ESP32 `protocol.h/.cpp` 改为匹配 STM32 当前 v0 协议。
   247|- ESP32 `config.h` 表情/动作 ID 临时映射到 STM32 当前定义，并补 `MQTT_REPORT_INTERVAL` 默认值。
   248|- STM32 IWDG reload 从非法 5000 改为 4095。
   249|- STM32 Error_Handler 不再持续喂狗，避免永不复位。
   250|- STM32 LED DMA buffer 放入 `.sram1`，`LED_SetExpression()` 改为立即启动一次 DMA 刷新。
   251|- ML `test_model.py` 修复 int8 量化先 astype 导致环绕的问题。
   252|- ML `train_emotion.py` 修复 class weight 在类别缺失时的标签错配。
   253|- ML `export_tflite.py` 生成 C 头文件时用 `MODEL_ALIGN` 宏兼容 C/C++。
   254|- `tools/flash_all.bat` 修复 `esport` -> `esptool` 拼写错误。
   255|
   256|## 8. 给下一个 AI/AI 工具的工作建议
   257|
   258|> 📖 **完整 AI 维护指南**: 参见 [AGENTS.md](AGENTS.md)
   259|
   260|1. 不要一上来重写架构。先让当前 v0 协议和现有模块上板跑通。
   261|2. 修改协议时必须同时改：
   262|   - `stm32/Core/Inc/protocol.h`
   263|   - `stm32/Core/Src/protocol.c`
   264|   - `esp32/src/protocol.h`
   265|   - `esp32/src/protocol.cpp`
   266|   - `docs/protocol.md`
   267|   - 本文件
   268|3. 表情/动作/触摸 ID 是高风险点，改任何一边都要查另一边。用 `python3 scripts/check_consistency.py` 验证。
   269|4. 文档里很多是目标态，不等于代码现实；以源码和本文件"当前真实状态"为准。
   270|5. 这个目录不是独立 git 仓库，父级 `/mnt/c/Users/24560` 看起来是 git 根。提交前必须先整理仓库边界，避免误提交用户目录。
   271|6. 离线验证命令：`python3 tests/test_protocol_v0.py && python3 scripts/check_consistency.py`
   272|7. ESP32 编译用 PlatformIO (espressif32@6.9.0 / Arduino 2.x / IDF 4.4)，在 WSL 的 /mnt/c 路径下很慢，建议在 Windows 端 VSCode PlatformIO 编译。
   273|

## 9. 文档与文件取舍

保留这 3 份就够了：
- `README.md`：给人看的项目总览和快速上手
- `MAINTAINERS.md`：给后续接手者的唯一入口
- `AGENTS.md`：给 AI 的硬约束/踩坑/决策记录

其他说明类文件只在“确实提供独立价值”时保留：
- `docs/hardware.md`：保留，作为装配/接线的单独参考
- `docs/architecture.md`：保留，作为架构图文档
- `docs/protocol.md`：保留但必须标注“v1 草案，当前不生效”
- `tools/flash_all.*`：保留，作为一键烧录脚本
- `*.pyc`：不要提交，删除即可
- 重复的维护说明如果和 MAINTAINERS/AGENTS 重复，优先删掉，不要多份同时维护

## 10. 以后硬件应该怎么做

### 第一阶段：先别上电
1. 先确认 BOM、接口、电平、供电是否和文档一致。
2. 先确认每个外设的“归属 MCU”没有接反。
3. 先确认 UART 交叉、共地、3.3V 逻辑电平。
4. 先确认舵机、LED、功放的 5V 电流预算，不靠开发板硬扛。

### 第二阶段：先单板后双板
1. ESP32 先单独编译通过。
2. STM32 先单独编译通过。
3. 再跑离线一致性测试：
   - `python3 tests/test_protocol_v0.py`
   - `python3 scripts/check_consistency.py`
4. 再做最小系统联调：UART → LED/舵机 → 触摸 → 麦克风 → 音频 → MQTT。

### 第三阶段：音频与资源
1. 先把 42 个 WAV 生成并上传 SPIFFS。
2. 上传前先确认 ESP32 侧能正常读到文件。
3. 音频不通先查：文件名、SPIFFS、I2S 引脚、采样率。

### 第四阶段：上板注意事项
1. 先备好串口日志，不要裸上。
2. 先限制舵机动作幅度，防止机械干涉。
3. 先测供电掉压，再测软件逻辑。
4. 任何新功能先写到维护入口，再改代码。

