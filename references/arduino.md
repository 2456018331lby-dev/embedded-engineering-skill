# Arduino 完整驱动参考

## 核心原则

生产项目慎用 Arduino，但原型验证和教学场景它是最快的路径。  
**关键纪律**：绝对不用 `delay()`；用 `millis()` 非阻塞计时；中断用 `volatile`。

---

## 非阻塞状态机模板（取代 delay 的正确方式）

```cpp
// 适用于任何需要"每隔 X 秒做一件事"的场景
class PeriodicTask {
public:
    PeriodicTask(uint32_t interval_ms) : _interval(interval_ms), _last(0) {}

    bool ready() {
        uint32_t now = millis();
        if (now - _last >= _interval) {
            _last = now;
            return true;
        }
        return false;
    }
private:
    uint32_t _interval, _last;
};

// 使用示例
PeriodicTask sensor_task(2000);   // 每 2 秒
PeriodicTask blink_task(500);     // 每 500ms

void loop() {
    if (sensor_task.ready()) {
        read_sensor();
    }
    if (blink_task.ready()) {
        digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
    }
}
```

---

## 常用传感器驱动

### DHT22 温湿度（软件时序，无需库）

```cpp
// dht22.h
#pragma once
#include <Arduino.h>

class DHT22 {
public:
    DHT22(uint8_t pin) : _pin(pin) {}

    struct Data {
        float temperature;
        float humidity;
        bool valid;
    };

    Data read() {
        Data result = {0, 0, false};
        uint8_t raw[5] = {0};

        // 发送起始信号
        pinMode(_pin, OUTPUT);
        digitalWrite(_pin, LOW);
        delay(1);  // 这里必须用 delay（协议要求）
        digitalWrite(_pin, HIGH);
        delayMicroseconds(30);
        pinMode(_pin, INPUT_PULLUP);

        // 等待 DHT22 响应
        if (!_wait_level(LOW, 80) || !_wait_level(HIGH, 80)) return result;

        // 读取 40 位数据
        for (int i = 0; i < 40; i++) {
            if (!_wait_level(LOW, 50)) return result;
            uint32_t high_us = _pulse_width(HIGH, 70);
            raw[i / 8] <<= 1;
            if (high_us > 35) raw[i / 8] |= 1;  // > 35µs → bit 1
        }

        // 校验和
        if (((raw[0] + raw[1] + raw[2] + raw[3]) & 0xFF) != raw[4])
            return result;

        result.humidity    = ((raw[0] << 8) | raw[1]) * 0.1f;
        result.temperature = (((raw[2] & 0x7F) << 8) | raw[3]) * 0.1f;
        if (raw[2] & 0x80) result.temperature *= -1;
        result.valid = true;
        return result;
    }

private:
    uint8_t _pin;

    bool _wait_level(uint8_t level, uint32_t timeout_us) {
        uint32_t start = micros();
        while (digitalRead(_pin) != level) {
            if (micros() - start > timeout_us) return false;
        }
        return true;
    }

    uint32_t _pulse_width(uint8_t level, uint32_t timeout_us) {
        uint32_t start = micros();
        while (digitalRead(_pin) == level) {
            if (micros() - start > timeout_us) return 0;
        }
        return micros() - start;
    }
};
```

### MPU6050 IMU（I2C，直接寄存器操作）

```cpp
// mpu6050.h
#pragma once
#include <Wire.h>

class MPU6050 {
public:
    static const uint8_t ADDR = 0x68;  // AD0 = LOW; HIGH → 0x69

    struct RawData { int16_t ax, ay, az, gx, gy, gz, temp; };
    struct ImuData { float ax, ay, az, gx, gy, gz, temp_c; };

    bool begin() {
        Wire.begin();
        _write(0x6B, 0x00);  // PWR_MGMT_1：唤醒，使用内部时钟
        _write(0x1A, 0x03);  // DLPF 44Hz
        _write(0x1B, 0x00);  // 陀螺仪 ±250°/s
        _write(0x1C, 0x00);  // 加速度 ±2g

        uint8_t who = _read(0x75);
        return (who == 0x68 || who == 0x70);  // WHO_AM_I
    }

    RawData read_raw() {
        Wire.beginTransmission(ADDR);
        Wire.write(0x3B);  // ACCEL_XOUT_H
        Wire.endTransmission(false);
        Wire.requestFrom((uint8_t)ADDR, (uint8_t)14);

        RawData d;
        auto r16 = [&]() -> int16_t {
            return (Wire.read() << 8) | Wire.read();
        };
        d.ax = r16(); d.ay = r16(); d.az = r16();
        d.temp = r16();
        d.gx = r16(); d.gy = r16(); d.gz = r16();
        return d;
    }

    ImuData read() {
        auto raw = read_raw();
        ImuData d;
        d.ax = raw.ax / 16384.0f;   // ±2g → ±1g = 16384 LSB/g
        d.ay = raw.ay / 16384.0f;
        d.az = raw.az / 16384.0f;
        d.gx = raw.gx / 131.0f;     // ±250°/s → 131 LSB/°/s
        d.gy = raw.gy / 131.0f;
        d.gz = raw.gz / 131.0f;
        d.temp_c = raw.temp / 340.0f + 36.53f;
        return d;
    }

private:
    void _write(uint8_t reg, uint8_t val) {
        Wire.beginTransmission(ADDR);
        Wire.write(reg); Wire.write(val);
        Wire.endTransmission();
    }
    uint8_t _read(uint8_t reg) {
        Wire.beginTransmission(ADDR);
        Wire.write(reg);
        Wire.endTransmission(false);
        Wire.requestFrom((uint8_t)ADDR, (uint8_t)1);
        return Wire.read();
    }
};
```

### HC-SR04 超声波测距

```cpp
// hcsr04.h
#pragma once
#include <Arduino.h>

class HCSR04 {
public:
    HCSR04(uint8_t trig, uint8_t echo) : _trig(trig), _echo(echo) {}

    void begin() {
        pinMode(_trig, OUTPUT);
        pinMode(_echo, INPUT);
        digitalWrite(_trig, LOW);
    }

    // 返回距离 mm；-1 表示超时（无回波）
    int32_t distance_mm() {
        digitalWrite(_trig, LOW);
        delayMicroseconds(2);
        digitalWrite(_trig, HIGH);
        delayMicroseconds(10);
        digitalWrite(_trig, LOW);

        uint32_t duration = pulseIn(_echo, HIGH, 30000);  // 30ms 超时
        if (duration == 0) return -1;
        // 声速 340 m/s = 0.34 mm/µs，来回 /2
        return (int32_t)(duration * 0.17f);
    }

private:
    uint8_t _trig, _echo;
};
```

---

## UART 自定义协议解析器（非阻塞）

```cpp
// protocol_parser.h
#pragma once
#include <Arduino.h>

// 帧格式：[0xAA][0x55][LEN][CMD][PAYLOAD...][CRC8]
class ProtocolParser {
public:
    static const uint8_t MAX_PAYLOAD = 64;

    struct Frame {
        uint8_t cmd;
        uint8_t payload[MAX_PAYLOAD];
        uint8_t len;
        bool valid;
    };

    // 在 loop() 中每次调用，返回是否收到完整帧
    bool feed(uint8_t byte) {
        switch (_state) {
            case IDLE:
                if (byte == 0xAA) _state = HDR1; break;
            case HDR1:
                _state = (byte == 0x55) ? LEN : IDLE; break;
            case LEN:
                if (byte > MAX_PAYLOAD) { _state = IDLE; break; }
                _len = byte; _idx = 0;
                _state = CMD; break;
            case CMD:
                _cmd = byte;
                _state = (_len > 0) ? PAYLOAD : CRC; break;
            case PAYLOAD:
                _buf[_idx++] = byte;
                if (_idx >= _len) _state = CRC; break;
            case CRC:
                _state = IDLE;
                if (_crc8_calc() == byte) {
                    _frame.cmd = _cmd;
                    _frame.len = _len;
                    memcpy(_frame.payload, _buf, _len);
                    _frame.valid = true;
                    return true;
                }
                break;
        }
        return false;
    }

    const Frame &frame() const { return _frame; }

    // 打包发送帧
    static void send(HardwareSerial &serial, uint8_t cmd,
                     const uint8_t *payload, uint8_t len) {
        serial.write(0xAA); serial.write(0x55);
        serial.write(len);  serial.write(cmd);
        if (payload) serial.write(payload, len);
        // CRC over [len][cmd][payload]
        uint8_t crc = crc8_chunk(len, cmd, payload, len);
        serial.write(crc);
    }

private:
    enum State { IDLE, HDR1, LEN, CMD, PAYLOAD, CRC } _state = IDLE;
    uint8_t _cmd, _len, _idx, _buf[MAX_PAYLOAD];
    Frame _frame = {};

    uint8_t _crc8_calc() {
        uint8_t crc = 0;
        auto step = [&](uint8_t b) {
            crc ^= b;
            for (int i = 0; i < 8; i++)
                crc = (crc & 0x80) ? (crc << 1) ^ 0x07 : (crc << 1);
        };
        step(_len); step(_cmd);
        for (uint8_t i = 0; i < _len; i++) step(_buf[i]);
        return crc;
    }

    static uint8_t crc8_chunk(uint8_t len, uint8_t cmd,
                               const uint8_t *data, uint8_t dlen) {
        uint8_t crc = 0;
        auto step = [&](uint8_t b) {
            crc ^= b;
            for (int i = 0; i < 8; i++)
                crc = (crc & 0x80) ? (crc << 1) ^ 0x07 : (crc << 1);
        };
        step(len); step(cmd);
        for (uint8_t i = 0; i < dlen; i++) step(data[i]);
        return crc;
    }
};
```

---

## 低功耗（AVR Arduino）

```cpp
// 推荐库：LowPower by Rocket Scream
// #include <LowPower.h>

void sleep_8s_loop(uint32_t total_seconds) {
    uint32_t elapsed = 0;
    while (elapsed < total_seconds) {
        uint32_t chunk = min((uint32_t)8, total_seconds - elapsed);
        // LowPower.powerDown(SLEEP_8S, ADC_OFF, BOD_OFF);  // 使用库
        // 若不用库，直接操作 WDT + SLEEP 寄存器：
        WDTCSR = (1 << WDCE) | (1 << WDE);
        WDTCSR = (1 << WDIE) | (1 << WDP3) | (1 << WDP0);  // 8s timeout
        SMCR = (1 << SM1) | (1 << SE);  // Power-down
        __asm__ __volatile__("sleep");
        SMCR &= ~(1 << SE);
        elapsed += chunk;
    }
}

ISR(WDT_vect) {}  // Watchdog 中断（防止复位）
```

---

## 常用库速查

| 用途 | 推荐库 |
|------|--------|
| OLED 显示 | Adafruit SSD1306 + GFX |
| TFT 彩屏 | TFT_eSPI（高性能）|
| DS18B20 温度 | DallasTemperature + OneWire |
| NRF24L01 无线 | RF24 by TMRh20 |
| JSON 解析 | ArduinoJson v7 |
| 低功耗 | LowPower by Rocket Scream |
| EEPROM | 内置 EEPROM.h（AVR）|
| PID 控制 | Arduino-PID-Library |
