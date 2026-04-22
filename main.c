#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "esp_http_server.h"
#include "driver/ledc.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_netif.h"
#include "lwip/ip4_addr.h"
#include "esp_adc/adc_oneshot.h"

static const char *TAG = "DISPENSADOR";

// --- CREDENCIALES WiFi ---
*/

// --- IP FIJA ---
#define STATIC_IP_0     192
#define STATIC_IP_1     168
#define STATIC_IP_2     137
#define STATIC_IP_3     100
#define STATIC_GW_3       1   /* gateway: 192.168.137.1 */

// --- HARDWARE ---
#define SERVO_GPIO      18
#define LED_GPIO         2   /* LED interno ESP32 DevKit V1 */
#define ADC_UNIT        ADC_UNIT_1
#define ADC_CHANNEL     ADC_CHANNEL_6      /* GPIO34 */
#define LEDC_TIMER      LEDC_TIMER_0
#define LEDC_MODE       LEDC_LOW_SPEED_MODE
#define LEDC_CHANNEL    LEDC_CHANNEL_0
#define LEDC_RES        LEDC_TIMER_13_BIT

// --- UART ---
#define UART_PORT       UART_NUM_0         /* mismo puerto que el monitor serial */
#define UART_BUF_SIZE   256

// --- TIEMPOS DE DISPENSADO (ciclos de 100ms) ---
#define TIEMPO_NIVEL_minimo    40   // niveles 1-3:  4 s
#define TIEMPO_NIVEL_BAJO    80   // niveles 4-5:  8 s
#define TIEMPO_NIVEL_MEDIO   140   // niveles 6-7:  14 s
#define TIEMPO_NIVEL_ALTO    180   // niveles 8-9:  18 s
#define TIEMPO_NIVEL_MAX    220   // nivel 10:    22 s

// --- UMBRALES FSR (medidos con R_fija = 100kΩ ∥ 11kΩ ≈ 9.91kΩ) ---
#define UMBRAL_VASO_MIN       700   // por debajo → no hay vaso
#define UMBRAL_VASO_VACIO     1200  // techo vaso vacío listo para dispensar
#define UMBRAL_VASO_LLENO     2950   // corte de llenado

// ── Handle global del ADC ────────────────────────────────────────────
adc_oneshot_unit_handle_t adc_handle;
static SemaphoreHandle_t disp_mutex = NULL;
static httpd_handle_t server = NULL;
/* ══════════════════════════════════════════════════════════════════════
 *  FUNCIONES AUXILIARES
 * ══════════════════════════════════════════════════════════════════════ */

static uint32_t angle_to_duty(int angle) {
    uint32_t us = 500 + (angle * (2400 - 500) / 180);
    return (uint32_t)((double)us * 8191 / 20000);
}

void mover_servo(int angulo) {
    ledc_set_duty(LEDC_MODE, LEDC_CHANNEL, angle_to_duty(angulo));
    ledc_update_duty(LEDC_MODE, LEDC_CHANNEL);
}

int leer_fsr(void) {
    int val = 0;
    ESP_ERROR_CHECK(adc_oneshot_read(adc_handle, ADC_CHANNEL, &val));
    return val;
}

/* ══════════════════════════════════════════════════════════════════════
 *  LÓGICA DE DISPENSADO — función compartida por WiFi y UART
 *
 *  Devuelve una cadena con el resultado para que cada canal
 *  la envíe por su propio medio (HTTP response o UART TX).
 * ══════════════════════════════════════════════════════════════════════ */
typedef enum {
    DISP_OK,
    DISP_ERR_NO_VASO,
    DISP_ERR_VASO_CON_LIQUIDO,
    DISP_ERR_OCUPADO, 
} disp_result_t;

static disp_result_t ejecutar_dispensado(int nivel_tristeza, const char *origen) {
    if (xSemaphoreTake(disp_mutex, 0) == pdFALSE) {          // ← línea 104
        ESP_LOGW(TAG, "[%s] Dispensado en curso. Rechazando.", origen);
        return DISP_ERR_OCUPADO;
    }
    int lectura = leer_fsr();
    ESP_LOGI(TAG, "[%s] FSR ADC: %d  |  nivel: %d", origen, lectura, nivel_tristeza);

    // Validar presencia y estado del vaso
    if (lectura < UMBRAL_VASO_MIN) {
        ESP_LOGW(TAG, "[%s] No hay vaso. ADC %d < %d", origen, lectura, UMBRAL_VASO_MIN);
        xSemaphoreGive(disp_mutex);
        return DISP_ERR_NO_VASO;
    }
    if (lectura > UMBRAL_VASO_VACIO) {
        ESP_LOGW(TAG, "[%s] Vaso con liquido. ADC %d > %d", origen, lectura, UMBRAL_VASO_VACIO);
        xSemaphoreGive(disp_mutex);
        return DISP_ERR_VASO_CON_LIQUIDO;
    }

    // Calcular timeout según nivel de tristeza
    int timeout_max;
    if (nivel_tristeza >= 10)       timeout_max = TIEMPO_NIVEL_MAX;
    else if (nivel_tristeza >= 8)   timeout_max = TIEMPO_NIVEL_ALTO;
    else if (nivel_tristeza >= 6)   timeout_max = TIEMPO_NIVEL_MEDIO;
    else if (nivel_tristeza >= 4)   timeout_max = TIEMPO_NIVEL_BAJO;
    else                            timeout_max = TIEMPO_NIVEL_minimo;

    ESP_LOGI(TAG, "[%s] Vaso vacio (ADC %d). Timeout: %d ciclos.", origen, lectura, timeout_max);

    // Abrir válvula + LED ON
    mover_servo(90);
    gpio_set_level(LED_GPIO, 1);

    // Bucle de llenado
    int timeout = 0;
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(100));
        lectura = leer_fsr();
        timeout++;

        if (lectura >= UMBRAL_VASO_LLENO) {
            ESP_LOGI(TAG, "[%s] Llenado completo. ADC: %d", origen, lectura);
            break;
        }
        if (lectura < (UMBRAL_VASO_MIN-400)) {
            ESP_LOGE(TAG, "[%s] EMERGENCIA: Vaso retirado. ADC: %d", origen, lectura);
            break;
        }
        if (timeout >= timeout_max) {
            ESP_LOGW(TAG, "[%s] Timeout (%d ciclos).", origen, timeout_max);
            break;
        }
    }

    // Cerrar válvula + LED OFF
    mover_servo(0);
    gpio_set_level(LED_GPIO, 0);
    xSemaphoreGive(disp_mutex);  
    return DISP_OK;
}

/* ══════════════════════════════════════════════════════════════════════
 *  CANAL WiFi — HTTP handler
 * ══════════════════════════════════════════════════════════════════════ */
esp_err_t bebida_handler(httpd_req_t *req) {
    // Leer parámetro ?nivel=X
    char query[32] = {0};
    int nivel = 5;
    if (httpd_req_get_url_query_str(req, query, sizeof(query)) == ESP_OK) {
        char param[8];
        if (httpd_query_key_value(query, "nivel", param, sizeof(param)) == ESP_OK)
            nivel = atoi(param);
    }
    if (nivel < 0 || nivel > 10) {
    httpd_resp_send(req, "ERROR: Nivel fuera de rango (0-10).", HTTPD_RESP_USE_STRLEN);
    return ESP_OK;
    }
    disp_result_t resultado = ejecutar_dispensado(nivel, "WiFi");

    switch (resultado) {
        case DISP_ERR_NO_VASO:
            httpd_resp_send(req, "ERROR: Coloque el vaso primero.", HTTPD_RESP_USE_STRLEN);
            break;
        case DISP_ERR_VASO_CON_LIQUIDO:
            httpd_resp_send(req, "ERROR: El vaso ya contiene liquido.", HTTPD_RESP_USE_STRLEN);
            break;
        default:
            httpd_resp_send(req, "OK: Proceso finalizado.", HTTPD_RESP_USE_STRLEN);
            break;
    }
    return ESP_OK;
}

/* ══════════════════════════════════════════════════════════════════════
 *  CANAL UART — tarea FreeRTOS
 *
 *  Protocolo esperado (mismo formato que la URL WiFi):
 *    "bebida?nivel=6\n"   ← enviar desde cualquier terminal serial
 *
 *  Respuestas por UART:
 *    "OK: Proceso finalizado.\n"
 *    "ERROR: Coloque el vaso primero.\n"
 *    "ERROR: El vaso ya contiene liquido.\n"
 *    "ERROR: Comando invalido. Usa: bebida?nivel=N (N=1-10)\n"
 * ══════════════════════════════════════════════════════════════════════ */
static void uart_task(void *arg) {
    uint8_t buf[UART_BUF_SIZE];

    while (true) {
        // Leer hasta newline o hasta llenar el buffer
        int len = uart_read_bytes(UART_PORT, buf, sizeof(buf) - 1,
                                  pdMS_TO_TICKS(100));
        if (len <= 0) continue;

        buf[len] = '\0';

        // Eliminar \r y \n del final
        for (int i = len - 1; i >= 0 && (buf[i] == '\r' || buf[i] == '\n'); i--)
            buf[i] = '\0';

        ESP_LOGI(TAG, "[UART] Recibido: '%s'", (char *)buf);

        // Verificar que empiece con "bebida"
        if (strncmp((char *)buf, "bebida", 6) != 0) {
            const char *err = "ERROR: Comando invalido. Usa: bebida?nivel=N (N=1-10)\n";
            uart_write_bytes(UART_PORT, err, strlen(err));
            continue;
        }

        // Extraer nivel del parámetro ?nivel=X
        int nivel = 5; // valor por defecto si no se especifica
        char *p = strstr((char *)buf, "nivel=");
        if (p) nivel = atoi(p + 6);

        // Validar rango
        if (nivel < 1 || nivel > 10) {
            const char *err = "ERROR: Nivel fuera de rango (1-10).\n";
            uart_write_bytes(UART_PORT, err, strlen(err));
            continue;
        }

        // Ejecutar dispensado y responder
        disp_result_t resultado = ejecutar_dispensado(nivel, "UART");
        const char *resp;
        switch (resultado) {
            case DISP_ERR_NO_VASO:
                resp = "ERROR: Coloque el vaso primero.\n";       break;
            case DISP_ERR_VASO_CON_LIQUIDO:
                resp = "ERROR: El vaso ya contiene liquido.\n";   break;
            default:
                resp = "OK: Proceso finalizado.\n";               break;
        }
        uart_write_bytes(UART_PORT, resp, strlen(resp));
    }
}

/* ══════════════════════════════════════════════════════════════════════
 *  INICIALIZACIONES
 * ══════════════════════════════════════════════════════════════════════ */
void init_hardware(void) {
    // 1. LED GPIO2
    gpio_config_t led_cfg = {
        .pin_bit_mask = (1ULL << LED_GPIO),
        .mode         = GPIO_MODE_OUTPUT,
        .pull_up_en   = GPIO_PULLUP_DISABLE,
        .pull_down_en = GPIO_PULLDOWN_DISABLE,
        .intr_type    = GPIO_INTR_DISABLE,
    };
    gpio_config(&led_cfg);
    gpio_set_level(LED_GPIO, 0);

    // 2. ADC OneShot
    adc_oneshot_unit_init_cfg_t adc_init = { .unit_id = ADC_UNIT };
    ESP_ERROR_CHECK(adc_oneshot_new_unit(&adc_init, &adc_handle));
    adc_oneshot_chan_cfg_t adc_chan = {
        .bitwidth = ADC_BITWIDTH_DEFAULT,
        .atten    = ADC_ATTEN_DB_12,
    };
    ESP_ERROR_CHECK(adc_oneshot_config_channel(adc_handle, ADC_CHANNEL, &adc_chan));

    // 3. Servo LEDC
    ledc_timer_config_t ledc_timer = {
        .speed_mode      = LEDC_MODE,
        .timer_num       = LEDC_TIMER,
        .duty_resolution = LEDC_RES,
        .freq_hz         = 50,
        .clk_cfg         = LEDC_AUTO_CLK,
    };
    ledc_timer_config(&ledc_timer);
    ledc_channel_config_t ledc_ch = {
        .speed_mode = LEDC_MODE,   .channel   = LEDC_CHANNEL,
        .timer_sel  = LEDC_TIMER,  .intr_type = LEDC_INTR_DISABLE,
        .gpio_num   = SERVO_GPIO,  .duty      = angle_to_duty(0),
        .hpoint     = 0,
    };
    ledc_channel_config(&ledc_ch);

    // 4. UART0 — comparte el puerto con el monitor serial (TX=GPIO1, RX=GPIO3)
    uart_config_t uart_cfg = {
        .baud_rate  = 115200,
        .data_bits  = UART_DATA_8_BITS,
        .parity     = UART_PARITY_DISABLE,
        .stop_bits  = UART_STOP_BITS_1,
        .flow_ctrl  = UART_HW_FLOWCTRL_DISABLE,
    };
    uart_param_config(UART_PORT, &uart_cfg);
    uart_driver_install(UART_PORT, UART_BUF_SIZE * 2, 0, 0, NULL, 0);
    
}

/* ══════════════════════════════════════════════════════════════════════
 *  WiFi EVENT HANDLER
 * ══════════════════════════════════════════════════════════════════════ */
static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                               int32_t event_id, void *event_data) {
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();

    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
    if (server != NULL) {
        httpd_stop(server);
        server = NULL;
    }
    ESP_LOGW(TAG, "WiFi desconectado. Reintentando...");
    esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = (ip_event_got_ip_t *)event_data;
        ESP_LOGI(TAG, "IP asignada: " IPSTR, IP2STR(&event->ip_info.ip));
        
        
        httpd_config_t config = HTTPD_DEFAULT_CONFIG();
        if (httpd_start(&server, &config) == ESP_OK) {
            httpd_uri_t uri = {
                .uri      = "/bebida",
                .method   = HTTP_GET,
                .handler  = bebida_handler,
                .user_ctx = NULL,
            };
            httpd_register_uri_handler(server, &uri);
            ESP_LOGI(TAG, "Servidor HTTP listo en http://%d.%d.%d.%d/bebida?nivel=N",
                     STATIC_IP_0, STATIC_IP_1, STATIC_IP_2, STATIC_IP_3);
        }
    }
}

/* ══════════════════════════════════════════════════════════════════════
 *  APP MAIN
 * ══════════════════════════════════════════════════════════════════════ */
void app_main(void) {
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES ||
    ret == ESP_ERR_NVS_NEW_VERSION_FOUND) {
    ESP_LOGW(TAG, "NVS corrupto, borrando...");
    ESP_ERROR_CHECK(nvs_flash_erase());
    ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK(ret);
    init_hardware();

    // Arrancar tarea UART (independiente del WiFi)
    disp_mutex = xSemaphoreCreateMutex(); 
    xTaskCreate(uart_task, "uart_task", 4096, NULL, 5, NULL);

    // Iniciar WiFi con IP estática
    esp_netif_init();
    esp_event_loop_create_default();
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    esp_wifi_init(&cfg);
    esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID,
                                        &wifi_event_handler, NULL, NULL);
    esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP,
                                        &wifi_event_handler, NULL, NULL);

    wifi_config_t wifi_config = {
        .sta = { .ssid = WIFI_SSID, .password = WIFI_PASS },
    };
    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_set_config(WIFI_IF_STA, &wifi_config);

    // IP fija — handle obtenido después de crear la interfaz STA
    esp_netif_t *netif = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    esp_netif_dhcpc_stop(netif);
    esp_netif_ip_info_t ip_info;
    IP4_ADDR(&ip_info.ip,      STATIC_IP_0, STATIC_IP_1, STATIC_IP_2, STATIC_IP_3);
    IP4_ADDR(&ip_info.gw,      STATIC_IP_0, STATIC_IP_1, STATIC_IP_2, STATIC_GW_3);
    IP4_ADDR(&ip_info.netmask, 255, 255, 255, 0);
    esp_netif_set_ip_info(netif, &ip_info);

    esp_wifi_start();

    ESP_LOGI(TAG, "Sistema listo. IP: %d.%d.%d.%d  |  UART: 'bebida?nivel=N'",
             STATIC_IP_0, STATIC_IP_1, STATIC_IP_2, STATIC_IP_3);
}