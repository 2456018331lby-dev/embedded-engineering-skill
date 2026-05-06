     1|# 抽象小陪伴机器人 (Abstract Companion Robot)
     2|
     3|> ESP32-S3 + STM32H743 双MCU架构的多模态情感陪伴机器人
     4|
     5|---
     6|
     7|## 项目概述
     8|
     9|抽象小陪伴机器人是一款面向桌面陪伴场景的智能硬件产品，采用 **ESP32-S3 + STM32H743** 双MCU异构架构。它能够通过麦克风采集语音、通过触摸传感器感知交互，并运行 TinyML 情绪识别模型，结合三种独特的"抽象人格"（曼波 / 哈基米 / 牢大），为用户提供个性化的情感陪伴体验。
    10|
    11|机器人具备 LED 矩阵表情显示和舵机肢体动作能力，配合用户记忆系统，能够越用越懂你，成为一个真正有"性格"的桌面伙伴。
    12|
    13|---
    14|
    15|## 核心特性
    16|
    17|| # | 特性 | 说明 |
    18||---|------|------|
    19|| 1 | **多模态情绪感知** | 麦克风语音情绪识别 + 电容触摸交互感知，双通道融合 |
    20|| 2 | **三种抽象人格** | 曼波（元气活泼）、哈基米（傲娇毒舌）、牢大（沉稳哲学），动态切换 |
    21|| 3 | **用户记忆系统** | 记录用户交互习惯与偏好，越用越懂你 |
    22|| 4 | **TinyML 情绪识别** | 基于 MFCC 特征提取 + 神经网络推理，在端侧实现实时情绪分类 |
    23|| 5 | **LED 表情 + 舵机动作** | 8x8 LED 矩阵显示表情，SG90 舵机驱动肢体动作 |
    24|
    25|---
    26|
    27|## 系统架构
    28|
    29|### 硬件架构
    30|
    31|```
    32|                    +------------------------------------------+
    33|                    |            抽象小陪伴机器人               |
    34|                    +------------------------------------------+
    35|                    |                                          |
    36|  +-----------+     |   +-------------+    +--------------+    |
    37|  | INMP441   | I2S |   |             |    |              |    |
    38|  | 麦克风    |---->|   |  STM32H743  |UART|   ESP32-S3   |    |
    39|  +-----------+     |   |  (感知层)    |--->|   (决策层)    |    |
    40|                    |   |             |    |              |    |
    41|  +-----------+     |   | - ADC采样   |    | - WiFi/BLE  |    |
    42|  | TTP223    |GPIO |   | - 音频预处理 |    | - 人格引擎   |    |
    43|  | 触摸传感器 |---->|   | - 特征提取   |    | - 记忆系统   |    |
    44|  +-----------+     |   | - 舵机控制   |    | - 对话管理   |    |
    45|                    |   | - LED驱动   |    | - OTA升级    |    |
    46|  +-----------+     |   +------+------+    +------+-------+    |
    47|  | SG90      | PWM |          |                  |            |
    48|  | 舵机 x2   |<----+          |                  |            |
    49|  +-----------+     |          |                  |            |
    50|                    |   +------+------+    +------+-------+    |
    51|  +-----------+     |   |  MAX98357A  |    |  Flash SPI   |    |
    52|  | WS2812B   | PWM |   |  I2S 功放   |    |  存储模型    |    |
    53|  | 表情矩阵  |<----+   +------+------+    +--------------+    |
    54|  +-----------+     |          |                                |
    55|                    |   +------+------+                         |
    56|                    |   |   喇叭      |                         |
    57|                    |   |  3W 8ohm    |                         |
    58|                    |   +-------------+                         |
    59|                    +------------------------------------------+
    60|                           |        |
    61|                      +----+--------+----+
    62|                      |   5V/3A 电源     |
    63|                      |  USB-C / 锂电池  |
    64|                      +-----------------+
    65|```
    66|
    67|### 软件架构
    68|
    69|```
    70|+------------------------------------------------------------------+
    71||                         ESP32-S3 决策层                           |
    72|+------------------------------------------------------------------+
    73||  +------------+  +-------------+  +-----------+  +------------+ |
    74||  | WiFi/BLE   |  | 人格引擎     |  | 记忆系统  |  | OTA 升级   | |
    75||  | 网络管理   |  | 曼波/哈基米  |  | 偏好记录  |  | 固件更新   | |
    76||  |            |  | /牢大切换    |  | 交互历史  |  |            | |
    77||  +------+-----+  +------+------+  +-----+-----+  +------+-----+ |
    78||         |                |               |               |       |
    79||  +------+----------------+---------------+---------------+-----+ |
    80||  |                    消息总线 (Message Bus)                    | |
    81||  +------+----------------+---------------+---------------+-----+ |
    82||         |                |               |               |       |
    83||  +------+-----+  +------+------+  +-----+-----+  +------+-----+ |
    84||  | UART 驱动  |  | 情绪决策     |  | 回复生成  |  | 音频播放   | |
    85||  | 与STM32通信|  | 状态机      |  | TTS/预录  |  | I2S输出    | |
    86||  +------------+  +-------------+  +-----------+  +------------+ |
    87|+------------------------------------------------------------------+
    88|            |  UART 921600bps  |
    89|            |  自定义帧协议     |
    90|            v                  v
    91|+------------------------------------------------------------------+
    92||                        STM32H743 感知层                           |
    93|+------------------------------------------------------------------+
    94||  +------------+  +-------------+  +-----------+  +------------+ |
    95||  | I2S 音频   |  | MFCC 特征   |  | 情绪分类  |  | 舵机 PWM   | |
    96||  | 采集驱动   |  | 提取 (CMSIS)|  | TinyML    |  | 控制       | |
    97||  | INMP441    |  | 48kHz/16bit |  | 推理      |  | SG90 x2   | |
    98||  +------+-----+  +------+------+  +-----+-----+  +------+-----+ |
    99||         |                |               |               |       |
   100||  +------+-----+  +------+------+  +-----+-----+  +------+-----+ |
   101||  | GPIO 中断  |  | SPI LED     |  | UART 协议 |  | ADC 电池   | |
   102||  | 触摸检测   |  | 8x8 矩阵    |  | 帧封装    |  | 电压检测   | |
   103||  | TTP223 x3  |  | 表情驱动    |  | CRC8校验  |  |            | |
   104||  +------------+  +-------------+  +-----------+  +------------+ |
   105|+------------------------------------------------------------------+
   106|```
   107|
   108|---
   109|
   110|## 情绪模型
   111|
   112|基于 Russell 环状模型 (Circumplex Model of Affect)，将情绪映射到二维空间：
   113|
   114|```
   115|            高唤醒度 (High Arousal)
   116|                 ^
   117|                 |
   118|       惊讶      |      兴奋
   119|     (Surprise)  |    (Excitement)
   120|                 |
   121|  负效价 ---------+---------+ 正效价
   122|  (Negative      |         (Positive
   123|   Valence)      |          Valence)
   124|                 |
   125|       悲伤      |      平静
   126|     (Sadness)   |    (Calmness)
   127|                 |
   128|                 v
   129|            低唤醒度 (Low Arousal)
   130|```
   131|
   132|三种人格对同一情绪输入有不同的响应策略：
   133|- **曼波**: 偏右上象限，永远积极向上，放大正效价
   134|- **哈基米**: 偏左上象限，傲娇式回应，先否定再关心
   135|- **牢大**: 偏下方象限，沉稳淡定，哲学式开导
   136|
   137|---
   138|
   139|## 硬件 BOM
   140|
   141|| 序号 | 器件 | 型号 | 数量 | 参考价格(元) | 备注 |
   142||------|------|------|------|-------------|------|
   143|| 1 | 主控 MCU | ESP32-S3-WROOM-1 (N16R8) | 1 | 25 | 16MB Flash, 8MB PSRAM |
   144|| 2 | 感知 MCU | STM32H743VIT6 (正点原子Apollo) | 1 | 180 | 开发板含外设 |
   145|| 3 | MEMS 麦克风 | INMP441 | 1 | 8 | I2S 数字输出 |
   146|| 4 | I2S 功放 | MAX98357A 模块 | 1 | 6 | 3W Class-D |
   147|| 5 | 喇叭 | 3W 8ohm 小喇叭 | 1 | 3 | 28mm 圆形 |
   148|| 6 | LED 矩阵 | WS2812B 8x8 模块 | 1 | 12 | RGB 全彩，单线控制 |
   149|| 7 | 触摸传感器 | TTP223 模块 | 1 | 2 | 电容式，带自锁/点动 |
   150|| 8 | 舵机 | SG90 微型舵机 | 2 | 8 | 9g，180度 |
   151|| 9 | 电源模块 | USB-C 5V/3A 降压模块 | 1 | 5 | 含锂电池充电 IC |
   152|| 10 | 锂电池 | 3.7V 2000mAh 18650 | 1 | 15 | 含保护板 |
   153|| 11 | 杜邦线/排线 | 公对母/母对母 | 若干 | 5 | |
   154|| 12 | 结构件 | 3D 打印外壳 | 1 | 30 | PLA 材质 |
   155|| | | | **合计** | **~296** | |
   156|
   157|---
   158|
   159|## 快速开始
   160|
   161|### 环境准备
   162|
   163|- **STM32 侧**: STM32CubeIDE 1.14+ 或 arm-none-eabi-gcc + Make
   164|- **ESP32 侧**: PlatformIO (`espressif32@6.9.0` / Arduino 2.x / IDF 4.4)
   165|- **ML 训练**: Python 3.10+, TensorFlow Lite, librosa
   166|- **离线测试**: Python 3.8+, 无第三方依赖
   167|
   168|### 编译烧录 - STM32
   169|
   170|```bash
   171|cd stm32/
   172|
   173|# 使用 Makefile 构建
   174|make -j$(nproc)
   175|
   176|# 烧录 (使用 ST-Link)
   177|make flash
   178|
   179|# 或使用 STM32CubeIDE
   180|# 打开项目 -> Build -> Run
   181|```
   182|
   183|### 编译烧录 - ESP32
   184|
   185|```bash
   186|cd esp32/
   187|
   188|# ESP-IDF 方式
   189|idf.py set-target esp32s3
   190|idf.py build
   191|idf.py -p /dev/ttyUSB0 flash monitor
   192|
   193|# PlatformIO 方式
   194|pio run -t upload
   195|pio device monitor
   196|```
   197|
   198|### 模型训练 (可选)
   199|
   200|```bash
   201|cd ml/
   202|pip install -r requirements.txt
   203|
   204|# 生成合成测试数据（开发用）
   205|python generate_test_data.py
   206|
   207|# 训练情绪识别模型
   208|python train_emotion.py --use_synthetic --model_path emotion_model.h5
   209|
   210|# 导出 INT8 TFLite 与 C 头文件
   211|python export_tflite.py --model_path emotion_model.h5 --output_path emotion_model.tflite
   212|
   213|# 测试推理
   214|python test_model.py --model emotion_model.tflite --audio datasets/synthetic/happy/happy_000.wav
   215|```
   216|
   217|---
   218|
   219|## 项目结构
   220|
   221|```
   222|tiny/
   223|├── README.md                   # 本文件
   224|├── AGENTS.md                   # AI 维护指南（目录、约定、踩坑清单）
   225|├── MAINTAINERS.md              # 维护入口（当前状态、验证命令）
   226|├── docs/                       # 项目文档
   227|│   ├── architecture.md         # 系统架构详解
   228|│   ├── protocol.md             # v1 协议草案（⚠️ 非当前代码）
   229|│   └── hardware.md             # 硬件指南
   230|
   231|├── stm32/                      # STM32H743 固件 (感知层, HAL裸机)
   232|│   └── Core/
   233|│       ├── Inc/                # 头文件
   234|│       │   ├── main.h          # 引脚表 + 外设句柄
   235|│       │   ├── protocol.h      # v0 UART 协议 (权威定义)
   236|│       │   ├── audio_capture.h # I2S2 DMA 音频采集
   237|│       │   ├── feature_extract.h # Goertzel 13频带特征
   238|│       │   ├── led_matrix.h    # WS2812B 8x8 表情矩阵
   239|│       │   ├── servo_ctrl.h    # SG90 舵机控制
   240|│       │   └── touch_sensor.h  # TTP223 触摸状态机
   241|│       └── Src/                # 实现文件 (与 Inc 一一对应)
   242|│
   243|├── esp32/                      # ESP32-S3 固件 (决策层, Arduino/PlatformIO)
   244|│   ├── include/config.h        # 全局配置（引脚、WiFi、MQTT、ID映射）
   245|│   ├── platformio.ini          # PlatformIO 构建配置
   246|│   └── src/
   247|│       ├── main.cpp            # 主循环 + WiFi/MQTT/调度
   248|│       ├── protocol.h/cpp      # v0 UART 协议 (镜像STM32)
   249|│       ├── emotion_engine.h/cpp # Russell环状模型情感引擎
   250|│       ├── personality.h/cpp   # 三重人格决策系统
   251|│       ├── memory_system.h/cpp # NVS 持久化 + 成就系统
   252|│       └── audio_player.h/cpp  # I2S WAV 播放 (IDF 4.4 legacy API)
   253|│
   254|├── scripts/
   255|│   └── check_consistency.py    # ESP32↔STM32 常量一致性检查
   256|├── tests/
   257|│   └── test_protocol_v0.py     # 离线协议测试 (22个)
   258|├── ml/                         # ML 训练/导出 (离线工具)
   259|│   ├── train_emotion.py
   260|│   ├── export_tflite.py
   261|│   ├── generate_test_data.py
   262|│   └── datasets/
   263|└── tools/
   264|    └── generate_audio.py       # TTS/测试音频生成
   265|```
   266|
   267|---
   268|
   269|## UART 通信协议
   270|
   271|双MCU通过 UART 921600bps 通信，采用 v0 帧协议：
   272|
   273|```
   274|+--------+--------+--------+-----------+--------+--------+
   275|| Header | Length | Type   | Payload   | CRC8   | Footer |
   276|| 0xAA   | 1 byte | 1 byte| 0~250 byte| 1 byte | 0x55   |
   277|+--------+--------+--------+-----------+--------+--------+
   278|Length = 整帧长度 = 5 + payload_len
   279|CRC8 = crc8([Length, Type, Payload...]), poly=0x07
   280|```
   281|
   282|> ⚠️ `docs/protocol.md` 描述的是计划中的 v1 协议，不等同当前代码。以代码为准。
   283|
   284|详细协议说明见 [docs/protocol.md](docs/protocol.md)，代码注释见 `protocol.h`。
   285|
   286|---
   287|
   288|## 维护入口
   289|
   290|后续维护者/AI 请优先阅读 [MAINTAINERS.md](MAINTAINERS.md)。该文件记录当前代码真实状态、v0 UART 协议、已知问题、验证命令和下一步优先级。
   291|
   292|面向 AI 的完整维护指南见 [AGENTS.md](AGENTS.md)。
   293|
   294|### 上板前预备工作清单（先做这些，再接硬件）
   295|
   296|1. 先统一当前真实实现，不按目标态文档接线：协议以代码里的 v0 为准，触摸按单路 TTP223 处理，不要按 README 旧描述的 `TTP223 x3` 和 v1 协议准备。
   297|2. 先分别确认两侧能独立编译：
   298|   - ESP32 固定使用 PlatformIO `espressif32@6.9.0`（Arduino 2.x / IDF 4.4），避免混用 IDF 5.x API。
   299|   - STM32 先补齐 HAL/CMSIS、`stm32h7xx_hal_conf.h`、Makefile 源文件和 `arm-none-eabi-gcc` 工具链。
   300|3. 先跑离线一致性检查，确认协议和 ID 映射没漂移：
   301|   - `python3 tests/test_protocol_v0.py`
   302|   - `python3 scripts/check_consistency.py`
   303|4. 先核对关键引脚和电平，再上电：
   304|   - STM32↔ESP32 UART：PA9/PA10 ↔ GPIO4/GPIO8，TX/RX 交叉，必须共地，3.3V 电平。
   305|   - INMP441 接 STM32 I2S2；MAX98357A 接 ESP32 I2S；不要把采集和播放接反。
   306|   - WS2812B 数据脚接 STM32 PA8；舵机接 PB6/PB7；触摸接 PC0。
   307|5. 先确认供电方案能承受负载：舵机、电源模块、LED、功放不要直接吃开发板弱供电；至少预留独立稳定 5V，STM32/ESP32 与外设共地，防止舵机动作时掉压复位。
   308|6. 先准备最小化联调顺序，不要一上来全量组装：
   309|   - 第一步只测双板 UART 收发。
   310|   - 第二步只测 STM32 LED/舵机输出。
   311|   - 第三步只测麦克风采集与音频播放。
   312|   - 最后再合并整机联调。
   313|7. 先准备上板观察手段：ESP32 串口日志、STM32 调试口/串口、万用表、电源电流观察；没有日志和供电观察手段时不要直接开始整机排障。
   314|
   315|离线验证：
   316|```bash
   317|python3 tests/test_protocol_v0.py         # 协议编解码 + CRC 测试 (22个)
   318|python3 scripts/check_consistency.py      # ESP32↔STM32 常量一致性检查
   319|```
   320|
   321|---
   322|
   323|## 许可证
   324|
   325|本项目采用 [MIT License](LICENSE) 开源。
   326|
   327|```
   328|MIT License
   329|
   330|Copyright (c) 2026 Abstract Companion Robot Project
   331|
   332|Permission is hereby granted, free of charge, to any person obtaining a copy
   333|of this software and associated documentation files (the "Software"), to deal
   334|in the Software without restriction, including without limitation the rights
   335|to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
   336|copies of the Software, and to permit persons to whom the Software is
   337|furnished to do so, subject to the following conditions:
   338|
   339|The above copyright notice and this permission notice shall be included in all
   340|copies or substantial portions of the Software.
   341|
   342|THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
   343|IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
   344|FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
   345|AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
   346|LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
   347|OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
   348|SOFTWARE.
   349|```
   350|
   351|---
   352|
   353|## 致谢
   354|
   355|- [Russell 环状模型](https://en.wikipedia.org/wiki/BPAD) - 情绪理论基础
   356|- [CMSIS-DSP](https://github.com/ARM-software/CMSIS-DSP) - MFCC 特征提取
   357|- [TensorFlow Lite Micro](https://github.com/tensorflow/tflite-micro) - 端侧推理引擎
   358|- [ESP-IDF](https://github.com/espressif/esp-idf) - ESP32 开发框架
   359|


---

## 文档怎么读

优先顺序：
1. `MAINTAINERS.md`：先看这里，知道当前状态和要做什么
2. `AGENTS.md`：给 AI 的硬约束和踩坑
3. `README.md`：看总体介绍与快速开始

不要同时维护多份重复的维护说明；如果内容重复，优先合并到 `MAINTAINERS.md`。

