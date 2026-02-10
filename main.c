#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "esp_http_server.h"
#include "driver/ledc.h"
#include "esp_adc/adc_oneshot.h" // <--- DRIVER MODERNO

static const char *TAG = "DISPENSADOR_WIFI";

// --- TUS CREDENCIALES ---
#define WIFI_SSID       ""
#define WIFI_PASS       ""

// --- HARDWARE ---
#define SERVO_GPIO              18
#define ADC_UNIT                ADC_UNIT_1
#define ADC_CHANNEL             ADC_CHANNEL_6 // GPIO 34
#define LEDC_TIMER              LEDC_TIMER_0
#define LEDC_MODE               LEDC_LOW_SPEED_MODE
#define LEDC_CHANNEL            LEDC_CHANNEL_0
#define LEDC_RES                LEDC_TIMER_13_BIT

// --- CALIBRACIÓN  ---

#define UMBRAL_VASO_PRESENTE    200  // Si baja de esto, hay vaso
#define UMBRAL_VASO_LLENO       3000  // Si baja de esto, está lleno

// Objeto para manejar el ADC
adc_oneshot_unit_handle_t adc_handle;

// Función Servo
static uint32_t angle_to_duty(int angle) {
    uint32_t us = 500 + (angle * (2400 - 500) / 180);
    return (uint32_t)((double)us * 8191 / 20000);
}

void mover_servo(int angulo) {
    ledc_set_duty(LEDC_MODE, LEDC_CHANNEL, angle_to_duty(angulo));
    ledc_update_duty(LEDC_MODE, LEDC_CHANNEL);
}

// Función ADC Moderna
int leer_fsr() {
    int val = 0;
    // Leemos usando el driver oneshot
    ESP_ERROR_CHECK(adc_oneshot_read(adc_handle, ADC_CHANNEL, &val));
    // ESP_LOGI(TAG, "Lectura FSR (GPIO34): %d", val); // Descomenta para depurar
    return val;
}

// --- SERVIDOR WEB ---
esp_err_t bebida_handler(httpd_req_t *req) {
    int lectura = leer_fsr();
    ESP_LOGI(TAG, "Peticion recibida. Sensor: %d", lectura);

    if (lectura < UMBRAL_VASO_PRESENTE) {
        ESP_LOGW(TAG, "ERROR: No hay vaso : %d)", lectura);
        httpd_resp_send(req, "ERROR: Coloque el vaso primero.", HTTPD_RESP_USE_STRLEN);
        return ESP_OK;
    }

    if (lectura >= UMBRAL_VASO_LLENO) {
        ESP_LOGW(TAG, "ERROR: Vaso ya lleno.");
        httpd_resp_send(req, "ERROR: El vaso ya esta lleno.", HTTPD_RESP_USE_STRLEN);
        return ESP_OK;
    }

    ESP_LOGI(TAG, "Vaso detectado. Abriendo valvula...");
    mover_servo(60); // Abrir

    // 3. Bucle de Llenado
    int timeout = 0;
    bool llenando = true;
    
    while (llenando) {
        vTaskDelay(pdMS_TO_TICKS(100)); 
        lectura = leer_fsr();
        timeout++;

        // Condición de Parada A: Peso alcanzado (Valor baja)
        if (lectura <= UMBRAL_VASO_LLENO) {
            ESP_LOGI(TAG, "EXITO: Llenado completo (%d)", lectura);
            llenando = false;
        }
        // Condición de Parada B: Vaso retirado (Valor sube a 4095)
        else if (lectura > UMBRAL_VASO_PRESENTE) {
            ESP_LOGE(TAG, "EMERGENCIA: Vaso retirado.");
            llenando = false;
        }
        // Condición de Parada C: Timeout (10 segundos)
        else if (timeout > 100) {
            ESP_LOGE(TAG, "TIMEOUT: Seguridad activada.");
            llenando = false;
        }
    }

    mover_servo(0); // Cerrar
    httpd_resp_send(req, "Proceso finalizado.", HTTPD_RESP_USE_STRLEN);
    return ESP_OK;
}

// --- INICIALIZACIONES ---
void init_hardware() {
    // 1. Configurar ADC OneShot (El nuevo estándar)
    adc_oneshot_unit_init_cfg_t init_config1 = {
        .unit_id = ADC_UNIT,
    };
    ESP_ERROR_CHECK(adc_oneshot_new_unit(&init_config1, &adc_handle));

    adc_oneshot_chan_cfg_t config = {
        .bitwidth = ADC_BITWIDTH_DEFAULT, // 12 bits
        .atten = ADC_ATTEN_DB_12,         // Rango completo 0-3.3V (aprox)
    };
    ESP_ERROR_CHECK(adc_oneshot_config_channel(adc_handle, ADC_CHANNEL, &config));

    // 2. Configurar Servo
    ledc_timer_config_t ledc_timer = {
        .speed_mode = LEDC_MODE, .timer_num = LEDC_TIMER,
        .duty_resolution = LEDC_RES, .freq_hz = 50, 
        .clk_cfg = LEDC_AUTO_CLK
    };
    ledc_timer_config(&ledc_timer);

    ledc_channel_config_t ledc_channel = {
        .speed_mode = LEDC_MODE, .channel = LEDC_CHANNEL,
        .timer_sel = LEDC_TIMER, .intr_type = LEDC_INTR_DISABLE,
        .gpio_num = SERVO_GPIO, .duty = angle_to_duty(0), 
        .hpoint = 0
    };
    ledc_channel_config(&ledc_channel);
}

// WiFi Event Handler (Sin cambios mayores)
static void wifi_event_handler(void* arg, esp_event_base_t event_base, int32_t event_id, void* event_data) {
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t* event = (ip_event_got_ip_t*) event_data;
        ESP_LOGI(TAG, "Conectado! IP: " IPSTR, IP2STR(&event->ip_info.ip));
        
        // Iniciar servidor web
        httpd_handle_t server = NULL;
        httpd_config_t config = HTTPD_DEFAULT_CONFIG();
        if (httpd_start(&server, &config) == ESP_OK) {
            httpd_uri_t uri_get = {
                .uri      = "/bebida",
                .method   = HTTP_GET,
                .handler  = bebida_handler,
                .user_ctx = NULL
            };
            httpd_register_uri_handler(server, &uri_get);
        }
    }
}

void app_main(void) {
    nvs_flash_init();
    init_hardware(); // Iniciar ADC y Servo

    // Iniciar WiFi
    esp_netif_init();
    esp_event_loop_create_default();
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    esp_wifi_init(&cfg);
    esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL, NULL);
    esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL, NULL);
    
    wifi_config_t wifi_config = {
        .sta = {
            .ssid = WIFI_SSID,
            .password = WIFI_PASS,
        },
    };
    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_set_config(WIFI_IF_STA, &wifi_config);
    esp_wifi_start();
}