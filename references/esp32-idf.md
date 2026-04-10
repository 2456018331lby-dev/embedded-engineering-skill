# ESP32 ESP-IDF 完整实现参考

## 工具链

**ESP-IDF v5.x**（推荐，LTS 支持）：`idf.py build flash monitor`  
**Arduino-ESP32**：适合快速原型，生产建议迁移 ESP-IDF  
**PlatformIO**：可同时支持两种框架

---

## Wi-Fi Station 连接 + 断线重连

```c
// wifi_manager.h
#ifndef WIFI_MANAGER_H
#define WIFI_MANAGER_H
#include "esp_wifi.h"
#include "esp_event.h"
#include "freertos/event_groups.h"

#define WIFI_SSID        "your_ssid"       // TODO: 改为实际 SSID
#define WIFI_PASSWORD    "your_password"   // TODO: 改为实际密码
#define WIFI_MAX_RETRY   5

#define WIFI_CONNECTED_BIT  BIT0
#define WIFI_FAIL_BIT       BIT1

bool wifi_init_sta(void);
bool wifi_is_connected(void);
#endif
```

```c
// wifi_manager.c
#include "wifi_manager.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include <string.h>

static const char *TAG = "wifi_mgr";
static EventGroupHandle_t s_wifi_event_group;
static int s_retry = 0;

static void event_handler(void *arg, esp_event_base_t base,
                           int32_t event_id, void *event_data) {
    if (base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        if (s_retry < WIFI_MAX_RETRY) {
            esp_wifi_connect();
            s_retry++;
            ESP_LOGW(TAG, "Retry Wi-Fi connection (%d/%d)", s_retry, WIFI_MAX_RETRY);
        } else {
            xEventGroupSetBits(s_wifi_event_group, WIFI_FAIL_BIT);
            ESP_LOGE(TAG, "Wi-Fi connection failed after %d retries", WIFI_MAX_RETRY);
        }
    } else if (base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = event_data;
        ESP_LOGI(TAG, "Got IP: " IPSTR, IP2STR(&event->ip_info.ip));
        s_retry = 0;
        xEventGroupSetBits(s_wifi_event_group, WIFI_CONNECTED_BIT);
    }
}

bool wifi_init_sta(void) {
    // NVS 初始化（Wi-Fi 依赖）
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES || ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        nvs_flash_init();
    }

    s_wifi_event_group = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));

    esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                         &event_handler, NULL, NULL);
    esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                         &event_handler, NULL, NULL);

    wifi_config_t wifi_config = {
        .sta = {
            .ssid     = WIFI_SSID,
            .password = WIFI_PASSWORD,
            .threshold.authmode = WIFI_AUTH_WPA2_PSK,
        },
    };
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wifi_config));
    ESP_ERROR_CHECK(esp_wifi_start());

    // 等待连接结果（最多 10 秒）
    EventBits_t bits = xEventGroupWaitBits(s_wifi_event_group,
                       WIFI_CONNECTED_BIT | WIFI_FAIL_BIT,
                       pdFALSE, pdFALSE, pdMS_TO_TICKS(10000));

    return (bits & WIFI_CONNECTED_BIT) != 0;
}

bool wifi_is_connected(void) {
    return (xEventGroupGetBits(s_wifi_event_group) & WIFI_CONNECTED_BIT) != 0;
}
```

---

## MQTT 完整实现（基于 esp-mqtt 组件）

```c
// mqtt_client_app.h
#ifndef MQTT_CLIENT_APP_H
#define MQTT_CLIENT_APP_H
#include <stdbool.h>
#include <stdint.h>

#define MQTT_BROKER_URI   "mqtt://192.168.1.100:1883"  // TODO: 改为实际 Broker
#define MQTT_TOPIC_PUB    "sensor/data"
#define MQTT_TOPIC_SUB    "sensor/cmd"
#define MQTT_CLIENT_ID    "esp32-node-001"

bool mqtt_app_start(void);
bool mqtt_publish(const char *topic, const char *payload, int qos, int retain);
void mqtt_set_message_callback(void (*cb)(const char *topic, const char *data, int len));
#endif
```

```c
// mqtt_client_app.c
#include "mqtt_client_app.h"
#include "mqtt_client.h"
#include "esp_log.h"
#include <string.h>

static const char *TAG = "mqtt_app";
static esp_mqtt_client_handle_t s_client = NULL;
static bool s_connected = false;
static void (*s_msg_cb)(const char *, const char *, int) = NULL;

static void mqtt_event_handler(void *arg, esp_event_base_t base,
                                int32_t event_id, void *event_data) {
    esp_mqtt_event_handle_t event = event_data;
    switch ((esp_mqtt_event_id_t)event_id) {
        case MQTT_EVENT_CONNECTED:
            s_connected = true;
            ESP_LOGI(TAG, "Connected to broker");
            esp_mqtt_client_subscribe(s_client, MQTT_TOPIC_SUB, 1);
            break;
        case MQTT_EVENT_DISCONNECTED:
            s_connected = false;
            ESP_LOGW(TAG, "Disconnected from broker");
            break;
        case MQTT_EVENT_DATA:
            if (s_msg_cb) {
                // event->data 不是 null 终止的，需要手动处理长度
                char topic[128] = {0}, data[512] = {0};
                int tlen = event->topic_len < 127 ? event->topic_len : 127;
                int dlen = event->data_len  < 511 ? event->data_len  : 511;
                memcpy(topic, event->topic, tlen);
                memcpy(data,  event->data,  dlen);
                s_msg_cb(topic, data, dlen);
            }
            break;
        case MQTT_EVENT_ERROR:
            ESP_LOGE(TAG, "MQTT error type: %d", event->error_handle->error_type);
            break;
        default:
            break;
    }
}

bool mqtt_app_start(void) {
    esp_mqtt_client_config_t cfg = {
        .broker.address.uri = MQTT_BROKER_URI,
        .credentials.client_id = MQTT_CLIENT_ID,
        .session.keepalive = 30,
    };
    s_client = esp_mqtt_client_init(&cfg);
    esp_mqtt_client_register_event(s_client, ESP_EVENT_ANY_ID,
                                    mqtt_event_handler, NULL);
    return esp_mqtt_client_start(s_client) == ESP_OK;
}

bool mqtt_publish(const char *topic, const char *payload, int qos, int retain) {
    if (!s_connected || !s_client) return false;
    int msg_id = esp_mqtt_client_publish(s_client, topic, payload, 0, qos, retain);
    return msg_id >= 0;
}

void mqtt_set_message_callback(void (*cb)(const char *, const char *, int)) {
    s_msg_cb = cb;
}
```

---

## OTA 固件升级（HTTP）

```c
// ota_updater.c
#include "esp_ota_ops.h"
#include "esp_http_client.h"
#include "esp_log.h"

static const char *TAG = "ota";

#define OTA_BUF_SIZE  4096
#define OTA_URL       "http://192.168.1.100/firmware.bin"  // TODO

esp_err_t ota_perform_update(const char *url) {
    esp_http_client_config_t http_cfg = {
        .url = url ? url : OTA_URL,
        .timeout_ms = 5000,
        .keep_alive_enable = true,
    };
    esp_http_client_handle_t client = esp_http_client_init(&http_cfg);

    const esp_partition_t *update_partition = esp_ota_get_next_update_partition(NULL);
    if (!update_partition) {
        ESP_LOGE(TAG, "No OTA partition found");
        return ESP_ERR_NOT_FOUND;
    }
    ESP_LOGI(TAG, "Writing to partition: %s", update_partition->label);

    esp_ota_handle_t ota_handle;
    ESP_ERROR_CHECK(esp_ota_begin(update_partition, OTA_SIZE_UNKNOWN, &ota_handle));

    esp_err_t err = esp_http_client_open(client, 0);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "HTTP open failed: %s", esp_err_to_name(err));
        esp_ota_abort(ota_handle);
        esp_http_client_cleanup(client);
        return err;
    }
    esp_http_client_fetch_headers(client);

    static char buf[OTA_BUF_SIZE];
    int total = 0, len;
    while ((len = esp_http_client_read(client, buf, OTA_BUF_SIZE)) > 0) {
        ESP_ERROR_CHECK(esp_ota_write(ota_handle, buf, len));
        total += len;
        ESP_LOGD(TAG, "Written %d bytes", total);
    }

    esp_http_client_close(client);
    esp_http_client_cleanup(client);

    if (esp_ota_end(ota_handle) != ESP_OK) {
        ESP_LOGE(TAG, "OTA end failed — image may be invalid");
        return ESP_FAIL;
    }

    ESP_ERROR_CHECK(esp_ota_set_boot_partition(update_partition));
    ESP_LOGI(TAG, "OTA complete (%d bytes). Rebooting...", total);
    esp_restart();
    return ESP_OK;  // unreachable
}
```

---

## BLE GATT Server（NimBLE，单特征值通知）

```c
// ble_server.c
#include "nimble/nimble_port.h"
#include "nimble/nimble_port_freertos.h"
#include "host/ble_hs.h"
#include "host/util/util.h"
#include "services/gap/ble_svc_gap.h"
#include "services/gatt/ble_svc_gatt.h"
#include "esp_log.h"

static const char *TAG = "ble_server";

// TODO: 替换为你的服务和特征值 UUID（可用 uuidgenerator.net 生成）
#define SERVICE_UUID    0x1234
#define CHAR_UUID_NOTIFY 0x5678

static uint16_t g_conn_handle = BLE_HS_CONN_HANDLE_NONE;
static uint16_t g_notify_handle;

static int char_access_cb(uint16_t conn_handle, uint16_t attr_handle,
                           struct ble_gatt_access_ctxt *ctxt, void *arg) {
    // 只读特征值：当主机读取时返回数据
    if (ctxt->op == BLE_GATT_ACCESS_OP_READ_CHR) {
        const char *value = "hello";
        os_mbuf_append(ctxt->om, value, strlen(value));
    }
    return 0;
}

static const struct ble_gatt_svc_def gatt_svcs[] = {
    {
        .type = BLE_GATT_SVC_TYPE_PRIMARY,
        .uuid = BLE_UUID16_DECLARE(SERVICE_UUID),
        .characteristics = (struct ble_gatt_chr_def[]) {
            {
                .uuid = BLE_UUID16_DECLARE(CHAR_UUID_NOTIFY),
                .access_cb = char_access_cb,
                .flags = BLE_GATT_CHR_F_READ | BLE_GATT_CHR_F_NOTIFY,
                .val_handle = &g_notify_handle,
            },
            { 0 }  // terminator
        },
    },
    { 0 }  // terminator
};

// 发送通知（从任意任务调用）
void ble_notify_send(const uint8_t *data, uint16_t len) {
    if (g_conn_handle == BLE_HS_CONN_HANDLE_NONE) return;
    struct os_mbuf *om = ble_hs_mbuf_from_flat(data, len);
    ble_gattc_notify_custom(g_conn_handle, g_notify_handle, om);
}

static void ble_app_on_sync(void) {
    ble_hs_id_infer_auto(0, NULL);
    ble_gatt_svc_init();
    ble_gatt_register_svcs(gatt_svcs, NULL, NULL);

    struct ble_hs_adv_fields fields = {0};
    const char *name = "ESP32-Node";
    fields.name = (uint8_t *)name;
    fields.name_len = strlen(name);
    fields.name_is_complete = 1;
    ble_gap_adv_set_fields(&fields);

    struct ble_gap_adv_params adv_params = {0};
    adv_params.conn_mode = BLE_GAP_CONN_MODE_UND;
    adv_params.disc_mode = BLE_GAP_DISC_MODE_GEN;
    ble_gap_adv_start(BLE_OWN_ADDR_PUBLIC, NULL, BLE_HS_FOREVER,
                      &adv_params, NULL, NULL);
    ESP_LOGI(TAG, "BLE advertising started");
}

void ble_server_init(void) {
    nimble_port_init();
    ble_svc_gap_init();
    ble_svc_gatt_init();
    ble_hs_cfg.sync_cb = ble_app_on_sync;
    nimble_port_freertos_init(nimble_port_run);
}
```

---

## Deep Sleep + RTC 定时唤醒

```c
// deep_sleep.c
#include "esp_sleep.h"
#include "esp_log.h"
#include "driver/rtc_io.h"

static const char *TAG = "sleep";

void enter_deep_sleep(uint64_t sleep_us) {
    ESP_LOGI(TAG, "Entering deep sleep for %llu us", sleep_us);

    // 配置 RTC 定时唤醒
    esp_sleep_enable_timer_wakeup(sleep_us);

    // 可选：配置 GPIO 唤醒（如按键）
    // esp_sleep_enable_ext0_wakeup(GPIO_NUM_0, 0);  // GPIO0 低电平唤醒

    // 释放不需要保持的外设
    // uart_flush_output(UART_NUM_0);
    // uart_driver_delete(UART_NUM_0);

    esp_deep_sleep_start();
    // 不会执行到这里
}

// 在 app_main 开头调用，检查唤醒原因
void check_wakeup_reason(void) {
    esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
    switch (cause) {
        case ESP_SLEEP_WAKEUP_TIMER:
            ESP_LOGI(TAG, "Wakeup by timer"); break;
        case ESP_SLEEP_WAKEUP_EXT0:
            ESP_LOGI(TAG, "Wakeup by GPIO"); break;
        default:
            ESP_LOGI(TAG, "Normal boot (not wakeup from sleep)"); break;
    }
}
```

---

## CMakeLists.txt 模板

```cmake
cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(my_esp32_project)
```

```cmake
# main/CMakeLists.txt
idf_component_register(
    SRCS
        "main.c"
        "wifi_manager.c"
        "mqtt_client_app.c"
    INCLUDE_DIRS "."
    REQUIRES
        esp_wifi
        mqtt
        esp_http_client
        app_update
        nvs_flash
        bt
        nimble
)
```
