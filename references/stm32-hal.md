# STM32 HAL 完整驱动参考

## 工具链与项目结构

**推荐工具链**：STM32CubeIDE（官方，集成 CubeMX）/ PlatformIO（跨平台）/ Keil MDK（商业）

**库优先级**：HAL（移植性好，原型首选）> LL（高效，批量生产）> 寄存器直操（特殊优化）

**项目结构**：
```
project/
├── Core/Inc/main.h, app_config.h, [module]_driver.h
├── Core/Src/main.c, [module]_driver.c, app_[feature].c
└── Drivers/STM32xxxx_HAL_Driver/   ← CubeMX 生成，不要手动修改
```

---

## UART — 完整驱动

### 阻塞发送（调试用）
```c
// uart_driver.h
#ifndef UART_DRIVER_H
#define UART_DRIVER_H
#include "main.h"
#include <stdint.h>

#define UART_TX_TIMEOUT_MS  100U

HAL_StatusTypeDef uart_send(const uint8_t *data, uint16_t len);
HAL_StatusTypeDef uart_send_str(const char *str);
void uart_printf(const char *fmt, ...);
#endif
```

```c
// uart_driver.c
#include "uart_driver.h"
#include <stdio.h>
#include <stdarg.h>
#include <string.h>

extern UART_HandleTypeDef huart2;  // TODO: 改为你的 UART 实例

HAL_StatusTypeDef uart_send(const uint8_t *data, uint16_t len) {
    return HAL_UART_Transmit(&huart2, data, len, UART_TX_TIMEOUT_MS);
}

HAL_StatusTypeDef uart_send_str(const char *str) {
    return uart_send((const uint8_t *)str, (uint16_t)strlen(str));
}

void uart_printf(const char *fmt, ...) {
    char buf[256];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    uart_send_str(buf);
}

// 重定向 printf 到 UART（在 main.c 中调用）
int __io_putchar(int ch) {
    HAL_UART_Transmit(&huart2, (uint8_t *)&ch, 1, UART_TX_TIMEOUT_MS);
    return ch;
}
```

### DMA 接收（生产推荐）
```c
// 在 CubeMX 中启用 UART RX DMA，并开启 UART IDLE line interrupt
// 在 main.c 中：
#define RX_BUF_SIZE  256U
uint8_t rx_dma_buf[RX_BUF_SIZE];

// 在 MX_USART2_UART_Init() 之后调用：
HAL_UARTEx_ReceiveToIdle_DMA(&huart2, rx_dma_buf, RX_BUF_SIZE);
__HAL_DMA_DISABLE_IT(&hdma_usart2_rx, DMA_IT_HT);  // 关半传输中断

// 回调（在 stm32xxxx_it.c 或单独文件中）
void HAL_UARTEx_RxEventCallback(UART_HandleTypeDef *huart, uint16_t Size) {
    if (huart->Instance == USART2) {
        // rx_dma_buf[0..Size-1] 是本次收到的数据
        process_rx_frame(rx_dma_buf, Size);
        // 重新启动 DMA 接收
        HAL_UARTEx_ReceiveToIdle_DMA(&huart2, rx_dma_buf, RX_BUF_SIZE);
        __HAL_DMA_DISABLE_IT(&hdma_usart2_rx, DMA_IT_HT);
    }
}
```

---

## SPI — 完整驱动（以 W25Q128 Flash 为例）

```c
// w25q_driver.h
#ifndef W25Q_DRIVER_H
#define W25Q_DRIVER_H
#include "main.h"

#define W25Q_CS_GPIO   GPIOA        // TODO: 改为你的 CS GPIO
#define W25Q_CS_PIN    GPIO_PIN_4   // TODO: 改为你的 CS Pin
#define W25Q_PAGE_SIZE 256U
#define W25Q_SECTOR_SIZE 4096U

typedef enum {
    W25Q_OK    = 0,
    W25Q_ERROR = 1,
    W25Q_BUSY  = 2,
} W25Q_Status;

W25Q_Status w25q_init(void);
W25Q_Status w25q_read_id(uint8_t *id_buf);  // 3 bytes
W25Q_Status w25q_read(uint32_t addr, uint8_t *buf, uint32_t len);
W25Q_Status w25q_write_page(uint32_t addr, const uint8_t *buf, uint16_t len);
W25Q_Status w25q_erase_sector(uint32_t addr);
#endif
```

```c
// w25q_driver.c
#include "w25q_driver.h"
#include <string.h>

extern SPI_HandleTypeDef hspi1;  // TODO: 改为你的 SPI 实例

#define CS_LOW()   HAL_GPIO_WritePin(W25Q_CS_GPIO, W25Q_CS_PIN, GPIO_PIN_RESET)
#define CS_HIGH()  HAL_GPIO_WritePin(W25Q_CS_GPIO, W25Q_CS_PIN, GPIO_PIN_SET)
#define SPI_TIMEOUT 100U

#define CMD_READ_ID     0x9FU
#define CMD_READ_DATA   0x03U
#define CMD_WRITE_EN    0x06U
#define CMD_PAGE_PROG   0x02U
#define CMD_SECTOR_ERASE 0x20U
#define CMD_READ_SR1    0x05U
#define SR1_BUSY_MASK   0x01U

static W25Q_Status w25q_wait_ready(uint32_t timeout_ms) {
    uint32_t start = HAL_GetTick();
    uint8_t cmd = CMD_READ_SR1, sr;
    while ((HAL_GetTick() - start) < timeout_ms) {
        CS_LOW();
        HAL_SPI_Transmit(&hspi1, &cmd, 1, SPI_TIMEOUT);
        HAL_SPI_Receive(&hspi1, &sr, 1, SPI_TIMEOUT);
        CS_HIGH();
        if (!(sr & SR1_BUSY_MASK)) return W25Q_OK;
        HAL_Delay(1);
    }
    return W25Q_BUSY;
}

W25Q_Status w25q_init(void) {
    CS_HIGH();
    HAL_Delay(10);
    return W25Q_OK;
}

W25Q_Status w25q_read_id(uint8_t *id_buf) {
    uint8_t cmd = CMD_READ_ID;
    CS_LOW();
    HAL_SPI_Transmit(&hspi1, &cmd, 1, SPI_TIMEOUT);
    HAL_SPI_Receive(&hspi1, id_buf, 3, SPI_TIMEOUT);
    CS_HIGH();
    return W25Q_OK;
}

W25Q_Status w25q_read(uint32_t addr, uint8_t *buf, uint32_t len) {
    uint8_t cmd[4] = {
        CMD_READ_DATA,
        (addr >> 16) & 0xFF,
        (addr >> 8) & 0xFF,
        addr & 0xFF,
    };
    CS_LOW();
    HAL_SPI_Transmit(&hspi1, cmd, 4, SPI_TIMEOUT);
    HAL_SPI_Receive(&hspi1, buf, len, SPI_TIMEOUT);
    CS_HIGH();
    return W25Q_OK;
}

W25Q_Status w25q_write_page(uint32_t addr, const uint8_t *buf, uint16_t len) {
    uint8_t we_cmd = CMD_WRITE_EN;
    uint8_t prog_cmd[4] = {
        CMD_PAGE_PROG,
        (addr >> 16) & 0xFF,
        (addr >> 8) & 0xFF,
        addr & 0xFF,
    };
    CS_LOW(); HAL_SPI_Transmit(&hspi1, &we_cmd, 1, SPI_TIMEOUT); CS_HIGH();
    CS_LOW();
    HAL_SPI_Transmit(&hspi1, prog_cmd, 4, SPI_TIMEOUT);
    HAL_SPI_Transmit(&hspi1, (uint8_t *)buf, len, SPI_TIMEOUT);
    CS_HIGH();
    return w25q_wait_ready(500);
}

W25Q_Status w25q_erase_sector(uint32_t addr) {
    uint8_t we_cmd = CMD_WRITE_EN;
    uint8_t erase_cmd[4] = {
        CMD_SECTOR_ERASE,
        (addr >> 16) & 0xFF,
        (addr >> 8) & 0xFF,
        addr & 0xFF,
    };
    CS_LOW(); HAL_SPI_Transmit(&hspi1, &we_cmd, 1, SPI_TIMEOUT); CS_HIGH();
    CS_LOW(); HAL_SPI_Transmit(&hspi1, erase_cmd, 4, SPI_TIMEOUT); CS_HIGH();
    return w25q_wait_ready(3000);
}
```

---

## I2C — 完整驱动（以 SHT31 温湿度传感器为例）

```c
// sht31_driver.h
#ifndef SHT31_DRIVER_H
#define SHT31_DRIVER_H
#include "main.h"

#define SHT31_I2C_ADDR  (0x44U << 1)  // ADDR pin low; high → 0x45<<1
#define SHT31_TIMEOUT   100U

typedef struct {
    float temperature_c;
    float humidity_pct;
} SHT31_Data;

HAL_StatusTypeDef sht31_init(void);
HAL_StatusTypeDef sht31_read(SHT31_Data *out);
#endif
```

```c
// sht31_driver.c
#include "sht31_driver.h"

extern I2C_HandleTypeDef hi2c1;  // TODO: 改为你的 I2C 实例

// 高重复度单次测量命令
#define SHT31_CMD_MEAS_HI_REP  0x2416U

static uint8_t sht31_crc8(const uint8_t *data, uint8_t len) {
    uint8_t crc = 0xFF;
    for (uint8_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (uint8_t b = 0; b < 8; b++)
            crc = (crc & 0x80) ? (crc << 1) ^ 0x31 : (crc << 1);
    }
    return crc;
}

HAL_StatusTypeDef sht31_init(void) {
    // 软复位
    uint8_t cmd[2] = {0x30, 0xA2};
    HAL_StatusTypeDef ret = HAL_I2C_Master_Transmit(
        &hi2c1, SHT31_I2C_ADDR, cmd, 2, SHT31_TIMEOUT);
    HAL_Delay(10);
    return ret;
}

HAL_StatusTypeDef sht31_read(SHT31_Data *out) {
    uint8_t cmd[2] = {
        (SHT31_CMD_MEAS_HI_REP >> 8) & 0xFF,
        SHT31_CMD_MEAS_HI_REP & 0xFF,
    };
    uint8_t raw[6];

    if (HAL_I2C_Master_Transmit(&hi2c1, SHT31_I2C_ADDR, cmd, 2, SHT31_TIMEOUT) != HAL_OK)
        return HAL_ERROR;

    HAL_Delay(20);  // 高重复度测量需要约 15ms

    if (HAL_I2C_Master_Receive(&hi2c1, SHT31_I2C_ADDR, raw, 6, SHT31_TIMEOUT) != HAL_OK)
        return HAL_ERROR;

    // CRC 校验
    if (sht31_crc8(raw, 2) != raw[2] || sht31_crc8(raw + 3, 2) != raw[5])
        return HAL_ERROR;

    uint16_t raw_t = ((uint16_t)raw[0] << 8) | raw[1];
    uint16_t raw_h = ((uint16_t)raw[3] << 8) | raw[4];
    out->temperature_c = -45.0f + 175.0f * (float)raw_t / 65535.0f;
    out->humidity_pct  = 100.0f * (float)raw_h / 65535.0f;
    return HAL_OK;
}
```

---

## ADC — 多通道 DMA 连续采样

```c
// adc_driver.h
#ifndef ADC_DRIVER_H
#define ADC_DRIVER_H
#include "main.h"

// TODO: 改为实际通道数（CubeMX 配置中开启的扫描通道数）
#define ADC_CHANNEL_COUNT  4U
#define ADC_SAMPLE_COUNT   16U  // 每通道平均采样次数（软件滤波）

extern volatile uint16_t adc_dma_buf[ADC_CHANNEL_COUNT * ADC_SAMPLE_COUNT];
extern volatile uint8_t  adc_data_ready;

void adc_start_dma(void);
uint16_t adc_get_average(uint8_t channel);
float adc_to_voltage(uint16_t raw, float vref);
#endif
```

```c
// adc_driver.c
#include "adc_driver.h"

extern ADC_HandleTypeDef hadc1;

volatile uint16_t adc_dma_buf[ADC_CHANNEL_COUNT * ADC_SAMPLE_COUNT];
volatile uint8_t  adc_data_ready = 0;

void adc_start_dma(void) {
    HAL_ADC_Start_DMA(&hadc1, (uint32_t *)adc_dma_buf,
                      ADC_CHANNEL_COUNT * ADC_SAMPLE_COUNT);
}

// DMA 传输完成回调（自动生成在 stm32xxxx_it.c，这里是逻辑实现）
void HAL_ADC_ConvCpltCallback(ADC_HandleTypeDef *hadc) {
    if (hadc->Instance == ADC1) {
        adc_data_ready = 1;
    }
}

uint16_t adc_get_average(uint8_t channel) {
    if (channel >= ADC_CHANNEL_COUNT) return 0;
    uint32_t sum = 0;
    for (uint8_t i = 0; i < ADC_SAMPLE_COUNT; i++)
        sum += adc_dma_buf[i * ADC_CHANNEL_COUNT + channel];
    return (uint16_t)(sum / ADC_SAMPLE_COUNT);
}

float adc_to_voltage(uint16_t raw, float vref) {
    return (float)raw * vref / 4095.0f;  // 12-bit ADC
}
```

---

## FreeRTOS 任务模板（STM32 + CubeMX 生成骨架）

```c
// freertos_tasks.c
#include "FreeRTOS.h"
#include "task.h"
#include "queue.h"
#include "semphr.h"
#include "sht31_driver.h"
#include "uart_driver.h"

// 任务句柄
static TaskHandle_t h_sensor_task  = NULL;
static TaskHandle_t h_comm_task    = NULL;
static TaskHandle_t h_led_task     = NULL;

// 队列：传感器数据从 sensor_task 发到 comm_task
static QueueHandle_t sensor_queue  = NULL;

// 消息结构
typedef struct {
    float temperature;
    float humidity;
    uint32_t timestamp;
} SensorMsg_t;

// ---- Sensor 任务：每 2 秒采集一次 ----
static void sensor_task(void *arg) {
    (void)arg;
    SHT31_Data data;
    SensorMsg_t msg;
    TickType_t last_wake = xTaskGetTickCount();

    for (;;) {
        if (sht31_read(&data) == HAL_OK) {
            msg.temperature = data.temperature_c;
            msg.humidity    = data.humidity_pct;
            msg.timestamp   = HAL_GetTick();
            // 非阻塞发送，若队列满则丢弃旧数据
            xQueueOverwrite(sensor_queue, &msg);
        } else {
            uart_printf("WARN: SHT31 read failed\r\n");
        }
        vTaskDelayUntil(&last_wake, pdMS_TO_TICKS(2000));
    }
}

// ---- Comm 任务：从队列取数据并发送 ----
static void comm_task(void *arg) {
    (void)arg;
    SensorMsg_t msg;

    for (;;) {
        if (xQueueReceive(sensor_queue, &msg, pdMS_TO_TICKS(5000)) == pdTRUE) {
            uart_printf("T=%.2f C, H=%.1f%%, t=%lu ms\r\n",
                        msg.temperature, msg.humidity, msg.timestamp);
        }
    }
}

// ---- LED 任务：心跳指示 ----
static void led_task(void *arg) {
    (void)arg;
    for (;;) {
        HAL_GPIO_TogglePin(GPIOC, GPIO_PIN_13);  // TODO: 改为你的 LED GPIO
        vTaskDelay(pdMS_TO_TICKS(500));
    }
}

// ---- 创建所有任务（在 main() 的 MX 初始化之后调用）----
void app_tasks_create(void) {
    // 使用 xQueueCreate 代替 xQueueCreateStatic 简化演示
    sensor_queue = xQueueCreate(1, sizeof(SensorMsg_t));
    configASSERT(sensor_queue != NULL);

    xTaskCreate(sensor_task, "Sensor", 256, NULL, 3, &h_sensor_task);
    xTaskCreate(comm_task,   "Comm",   256, NULL, 2, &h_comm_task);
    xTaskCreate(led_task,    "LED",    128, NULL, 1, &h_led_task);
}
```

---

## Stop Mode 低功耗（STM32 最常用）

```c
// lowpower.c
#include "main.h"

// 进入 Stop Mode，等待外部中断或 RTC 唤醒
void enter_stop_mode(uint32_t sleep_seconds) {
    // 配置 RTC 唤醒（需要 CubeMX 启用 RTC WakeUp）
    HAL_RTCEx_SetWakeUpTimer_IT(&hrtc, sleep_seconds,
                                 RTC_WAKEUPCLOCK_CK_SPRE_16BITS);

    // 关闭不需要的外设时钟（按需添加）
    __HAL_RCC_GPIOB_CLK_DISABLE();

    // 进入 Stop Mode 2（最低漏电流 LDO 模式）
    HAL_PWREx_EnterSTOP2Mode(PWR_STOPENTRY_WFI);

    // 唤醒后重新配置系统时钟（Stop Mode 会降频到 MSI）
    SystemClock_Config();

    // 重新启用外设时钟
    __HAL_RCC_GPIOB_CLK_ENABLE();

    // 关闭 RTC 唤醒
    HAL_RTCEx_DeactivateWakeUpTimer(&hrtc);
}
```

---

## 系列选型速查

| 系列 | 核心 | 主频 | 典型应用 |
|------|------|------|----------|
| F0/G0 | M0/M0+ | 64MHz | 低成本家电控制 |
| F1 | M3 | 72MHz | 经典入门（Blue Pill）|
| F4 | M4F | 168MHz | 高性能DSP/音频 |
| G4 | M4F | 170MHz | 电机/电源控制（推荐新设计）|
| H7 | M7 | 480MHz | 机器视觉/以太网/双核 |
