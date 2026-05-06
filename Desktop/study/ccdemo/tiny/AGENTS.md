     1|# AGENTS.md — AI 维护指南（给下一个 AI 看的）
     2|
     3|> **项目**: 抽象小陪伴机器人 (Tiny Companion Robot)
     4|> **最后更新**: 2026-05-03
     5|> **状态**: 原型开发中期，双板通信已通，音频播放待硬件验证
     6|
     7|---
     8|
     9|## 1. 项目一句话
    10|
    11|双 MCU（STM32H743 感知 + ESP32-S3 决策）的桌面陪伴机器人，有情感引擎、三重人格（曼波/哈基米/牢大）、LED 表情矩阵、舵机动作、语音播放和 MQTT 上报能力。
    12|
    13|---
    14|
    15|## 2. 目录结构速览
    16|
    17|```
    18|tiny/
    19|├── esp32/                   # ESP32-S3 决策层 (Arduino/PlatformIO)
    20|│   ├── include/config.h     # 全局配置（引脚、WiFi、MQTT、表情/动作ID）
    21|│   ├── platformio.ini       # PlatformIO 构建配置
    22|│   └── src/
    23|│       ├── main.cpp         # 主循环、WiFi/MQTT/调度
    24|│       ├── protocol.h/cpp   # UART 协议（v0 实际协议）
    25|│       ├── emotion_engine.h/cpp  # Russell 环状模型情感引擎
    26|│       ├── personality.h/cpp     # 三重人格决策系统
    27|│       ├── memory_system.h/cpp   # NVS 持久化 + 成就系统
    28|│       └── audio_player.h/cpp    # I2S WAV 播放（IDF 4.4 legacy API）
    29|├── stm32/                   # STM32H743 感知层 (HAL 库/裸机)
    30|│   └── Core/
    31|│       ├── Inc/             # 头文件
    32|│       │   ├── main.h       # 引脚表 + 外设句柄 extern
    33|│       │   ├── protocol.h   # 协议定义（权威来源）
    34|│       │   ├── audio_capture.h
    35|│       │   ├── feature_extract.h
    36|│       │   ├── touch_sensor.h
    37|│       │   ├── led_matrix.h
    38|│       │   └── servo_ctrl.h
    39|│       └── Src/             # 实现
    40|│           ├── main.c       # 主循环 + 外设初始化 + 命令分发
    41|│           ├── protocol.c   # 协议解析 + CRC8 查表
    42|│           ├── audio_capture.c    # I2S2 DMA ping-pong
    43|│           ├── feature_extract.c  # Goertzel 13频带 + RMS/ZCR
    44|│           ├── touch_sensor.c     # TTP223 状态机（单/长/双击）
    45|│           ├── led_matrix.c       # WS2812B 8x8 TIM+DMA 驱动
    46|│           └── servo_ctrl.c       # SG90 TIM4 PWM + 手势序列
    47|├── docs/                    # 设计文档
    48|│   ├── architecture.md      # 系统架构（含数据流图）
    49|│   ├── hardware.md          # 硬件 BOM + 接线 + 装配
    50|│   └── protocol.md          # ⚠️ 这是 v1 计划协议，不是当前代码
    51|├── tests/
    52|│   └── test_protocol_v0.py  # 离线协议一致性测试
    53|├── ml/                      # ML 训练脚本（离线用）
    54|├── tools/
    55|│   └── generate_audio.py    # TTS/测试音频生成
    56|├── MAINTAINERS.md           # 维护入口
    57|└── AGENTS.md                # ← 你在看的这个文件
    58|```
    59|
    60|---
    61|
    62|## 3. 关键约定（必须知道）
    63|
    64|### 3.1 协议：v0 是唯一真实协议
    65|
    66|代码中的帧格式：
    67|```
    68|[0xAA] [Length] [Type] [Payload...] [CRC8] [0x55]
    69|```
    70|- Length = 整帧长度 = 5 + payload_len（最小 5）
    71|- CRC8 = crc8([Length, Type, Payload...])，多项式 0x07
    72|- **STM32 protocol.h 是权威定义**，ESP32 protocol.h/cpp 镜像
    73|
    74|⚠️ `docs/protocol.md` 描述的是 v1 **计划协议**（有 CMD 字段、TYPE 区分请求/通知等），**当前代码不使用**。如果你要改协议，以代码为准。
    75|
    76|### 3.2 平台/工具链
    77|
    78|| 侧 | 平台 | 工具链 | 构建工具 |
    79||----|------|--------|---------|
    80|| ESP32 | ESP32-S3-DevKitC-1 | Arduino-ESP32 v2.x (IDF 4.4) | PlatformIO |
    81|| STM32 | 正点原子 Apollo H743 | STM32Cube HAL | STM32CubeIDE / Keil |
    82|
    83|**重要**: ESP32 用的是 `espressif32@6.9.0`（Arduino 2.x / IDF 4.4），**不是** IDF 5.x。audio_player.cpp 已改为 legacy `i2s_write()` API。
    84|
    85|### 3.3 表情 ID 映射
    86|
    87|| ESP32 名 | 值 | STM32 LED 表情 | 备注 |
    88||----------|---|---------------|------|
    89|| EXPR_NEUTRAL | 0 | NEUTRAL | |
    90|| EXPR_HAPPY | 1 | SMILE | |
    91|| EXPR_SAD | 3 | CONFUSED | STM32 没有 SAD |
    92|| EXPR_ANGRY | 6 | ANGRY | |
    93|| EXPR_CONFUSED | 3 | CONFUSED | 与 SAD 共用 |
    94|| EXPR_SLEEPY | 5 | SLEEPING | |
    95|| EXPR_EXCITED | 7 | SURPRISED | STM32 没有 EXCITED |
    96|| EXPR_CALM | 0 | NEUTRAL | |
    97|
    98|### 3.4 动作 ID 映射
    99|
   100|| ESP32 名 | 值 | STM32 舵机手势 |
   101||----------|---|--------------|
   102|| ACTION_NONE | 0 | GESTURE_NONE |
   103|| ACTION_NOD | 1 | GESTURE_NOD |
   104|| ACTION_SHAKE | 2 | GESTURE_SHAKE |
   105|| ACTION_DANCE / ACTION_LOOK_AROUND | 3 | GESTURE_LOOK_AROUND |
   106|| ACTION_YAWN / ACTION_LEAN_IN | 4 | GESTURE_TILT_HEAD |
   107|
   108|### 3.5 引脚速查
   109|
   110|**STM32**（见 `stm32/Core/Inc/main.h`）:
   111|- UART1: PA9(TX) / PA10(RX) → ESP32, 921600 baud
   112|- I2S2: PB12(WS) / PB13(CK) / PB15(SD) → INMP441
   113|- LED: PA8 (TIM1_CH1) → WS2812B
   114|- Touch: PC0 → TTP223
   115|- Servo: PB6(PAN) / PB7(TILT) → TIM4
   116|
   117|**ESP32**（见 `esp32/include/config.h`）:
   118|- UART1: GPIO8(TX) / GPIO4(RX) → STM32, 921600
   119|- I2S: GPIO15(BCLK) / GPIO16(LRCLK) / GPIO17(DOUT) → MAX98357A
   120|- LED: GPIO48 (板载 RGB)
   121|- WiFi/MQTT 可选，留空则离线运行
   122|
   123|---
   124|
   125|## 4. 修 bug 的优先级路线
   126|
   127|### P0: 编译阻断
   128|- audio_player.cpp IDF5→IDF4.4 ← **已修复 (2026-05-03)**
   129|- 如遇新编译错误，先检查 `platformio.ini` 的 `platform` 版本
   130|
   131|### P1: 协议一致性
   132|- 运行 `python3 tests/test_protocol_v0.py` 离线验证
   133|- 对比 `esp32/src/protocol.h` 和 `stm32/Core/Inc/protocol.h` 的消息类型/常量
   134|
   135|### P2: 情感/人格逻辑
   136|- emotion_engine.cpp 象限分类阈值(±0.3)可调
   137|- personality.cpp 语音池通过 `PhrasePool` 结构管理
   138|- 触摸别名: TOUCH_SHORT_TAP/HEAD=1, LONG_PRESS/PAT=2, DOUBLE_TAP/SQUEEZE=3
   139|
   140|### P3: 新功能
   141|- 新增表情: 在 stm32 led_matrix.c 加位图 + EXPR_COUNT++，ESP32 config.h 对齐
   142|- 新增人格: 在 personality.cpp 加 PersonalityType 枚举 + _defs 数组
   143|- 新增触摸类型: touch_sensor.c 状态机 + protocol 消息类型
   144|
   145|---
   146|
   147|## 5. 常见踩坑
   148|
   149|1. **STM32 DMA 缓冲必须在 SRAM1**（D2 域），不能放 DTCM 或 AXI SRAM，否则 DMA 访问不到
   150|2. **ESP32 UART RX 用 GPIO4**（不是 GPIO18），否则和 USB-JTAG 冲突
   151|3. **i2s_write() vs i2s_channel_write()**: IDF 4.4 用前者，IDF 5.x 用后者。当前用 4.4
   152|4. **millis() 溢出**: 代码统一用 `(int32_t)(now - last)` 处理 49 天溢出
   153|5. **MQTT_REPORT_INTERVAL** 在 config.h 和 platformio.ini 中都有定义，platformio.ini 的 `-D` 标志优先
   154|6. **config.h 的 DEBUG_SERIAL 和 PROTOCOL_SERIAL**: ESP32-S3 板上 Serial=USB CDC, Serial1=UART1
   155|
   156|---
   157|
   158|## 6. 如何验证你的改动
   159|
   160|### 上板前预备工作清单（硬件前必须先完成）
   161|
   162|1. 先确认协议、引脚、外设分工都按当前代码，不按旧规划：
   163|   - 通信只认 v0 帧协议。
   164|   - 触摸按单路 TTP223 处理。
   165|   - 麦克风挂 STM32，功放挂 ESP32，不能接反。
   166|2. 先让两侧都能单独通过基础验证：
   167|   - ESP32 至少 `pio run` 成功。
   168|   - STM32 至少能在本地工程里通过编译/链接。
   169|3. 先跑离线检查再上板：
   170|   - `python3 tests/test_protocol_v0.py`
   171|   - `python3 scripts/check_consistency.py`
   172|4. 先核对接线和供电：
   173|   - UART 交叉、3.3V 电平、共地。
   174|   - 舵机/LED/功放单独看 5V 负载能力，不要直接依赖开发板弱供电。
   175|   - DMA/I2S 相关外设保持与文档引脚一致，避免因为错脚位误判代码问题。
   176|5. 先按最小系统分步联调：UART → LED/舵机 → 触摸 → 麦克风 → 音频播放 → 整机。
   177|6. 先准备日志和测量手段：ESP32 串口监视器、STM32 调试口/串口、万用表、电流观察。
   178|
   179|```bash
   180|# ESP32 编译（在 esp32/ 目录下）
   181|cd esp32
   182|pio run              # 只编译不上传
   183|pio run -t upload    # 编译+上传
   184|pio device monitor   # 串口监视器
   185|
   186|# 协议离线测试（在项目根目录）
   187|python3 tests/test_protocol_v0.py
   188|
   189|# STM32 需要在 STM32CubeIDE 中编译
   190|# 文件在 stm32/ 目录下，导入后编译即可
   191|```
   192|
   193|---
   194|
   195|## 7. 当前待办 / 已知问题
   196|
   197|| # | 问题 | 优先级 | 状态 |
   198||---|------|--------|------|
   199|| 1 | ESP32 按钮长按切换人格逻辑被遗漏 | P2 | 待确认 |
   200|| 2 | MQTT 缺少 stats/achievement 报文发送 | P2 | 仅 emotion topic |
   201|| 3 | personality.cpp 中 `ACTION_DANCE=3` 实际映射 LOOK_AROUND | P2 | 设计决策 |
   202|| 4 | docs/protocol.md 是 v1 计划，需要标注或重写 | P3 | 本会话修正 |
   203|| 5 | audio_player 需硬件实测 | P1 | 等组装 |
   204|| 6 | ML 训练脚本未集成到固件 | P3 | 离线工具 |
   205|
   206|---
   207|
   208|## 8. 提交规范
   209|
   210|```
   211|<scope>: <description>
   212|
   213|scope: stm32, esp32, docs, tests, tools, ml
   214|```
   215|
   216|示例：
   217|```
   218|esp32: 修复 I2S 播放兼容 IDF 4.4 legacy API
   219|stm32: 添加 LED 过渡动画
   220|docs: 更新协议文档匹配 v0 实际实现
   221|```
   222|


## 5. 交接原则

- 只维护一套主入口：`README.md` + `MAINTAINERS.md` + `AGENTS.md`
- 重复说明要删，不要在多个文档里各写一遍
- `docs/protocol.md` 只是草案，当前代码以 `protocol.h` 为准
- `*.pyc`、临时缓存、编译产物不进仓库
- 以后如果要上硬件，先看 MAINTAINERS.md 的“上板前预备工作清单”

