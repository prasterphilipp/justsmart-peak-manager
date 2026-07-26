"""Constants for JustSmart Peak Manager."""

from homeassistant.const import Platform

DOMAIN = "justsmart_peak_manager"
NAME = "JustSmart Peak Manager"
VERSION = "0.1.0"
PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SELECT, Platform.BUTTON]

CONF_GRID_POWER_ENTITY = "grid_power_entity"
CONF_POWER_POLARITY = "power_polarity"
CONF_TARGET_KW = "target_kw"
CONF_WARNING_MARGIN_KW = "warning_margin_kw"
CONF_PROTECT_MONTHLY_PEAK = "protect_monthly_peak"
CONF_WALLBOX_CURRENT_ENTITY = "wallbox_current_entity"
CONF_WALLBOX_SWITCH_ENTITY = "wallbox_switch_entity"
CONF_WALLBOX_MIN_A = "wallbox_min_a"
CONF_WALLBOX_MAX_A = "wallbox_max_a"
CONF_WALLBOX_PHASES = "wallbox_phases"
CONF_VOLTAGE = "voltage"
CONF_RESTORE_STEP_A = "restore_step_a"
CONF_LOAD_ENTITY = "load_{index}_entity"
CONF_LOAD_POWER = "load_{index}_power_kw"
CONF_LOAD_NAME = "load_{index}_name"

DEFAULT_TARGET_KW = 4.5
DEFAULT_WARNING_MARGIN_KW = 0.5
DEFAULT_WALLBOX_MIN_A = 6
DEFAULT_WALLBOX_MAX_A = 16
DEFAULT_WALLBOX_PHASES = 3
DEFAULT_VOLTAGE = 230
DEFAULT_RESTORE_STEP_A = 1
DEFAULT_MODE = "monitor"
MODES = ["monitor", "automatic"]
POWER_POLARITIES = ["import_positive", "import_negative"]
UPDATE_INTERVAL_SECONDS = 5
CONTROL_COOLDOWN_SECONDS = 10
STORAGE_SAVE_INTERVAL_SECONDS = 30
STORAGE_VERSION = 2
STORAGE_KEY = f"{DOMAIN}.state"
FRONTEND_FILE = "justsmart-peak-manager-card.js"
FRONTEND_TARGET_DIR = "www/justsmart_peak_manager"
FRONTEND_URL = "/local/justsmart_peak_manager/justsmart-peak-manager-card.js"
FRONTEND_RESOURCE_ID = "justsmart_peak_manager_card"
