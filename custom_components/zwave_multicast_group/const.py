"""Constants for Z-Wave Multicast Group (no Home Assistant imports)."""

DOMAIN = "zwave_multicast_group"

CONF_ENTITIES = "entities"
CONF_GROUP_TYPE = "group_type"
CONF_TRAVEL_TIME = "travel_time"
CONF_VERIFY_DELAY = "verify_delay"

# One config entry = one group of one domain, like HA's own group helper.
GROUP_TYPES = ["cover", "fan", "light", "switch"]

# Covers: the group shows opening/closing for this long, then verifies.
DEFAULT_TRAVEL_TIME = 60  # seconds, end to end
MIN_TRAVEL_TIME = 5
MAX_TRAVEL_TIME = 600

# Lights, switches, fans don't travel: verify this long after the multicast (a light's
# transition is added on top).
DEFAULT_VERIFY_DELAY = 5  # seconds
MIN_VERIFY_DELAY = 1
MAX_VERIFY_DELAY = 120

# After the travel time / verify delay, ask each multicast member for its real value and
# give the reports this long to arrive before deciding which ones missed the frame.
VERIFY_REPORT_WAIT = 3  # seconds
POSITION_TOLERANCE = 2  # percent (cover position, fan percentage)
LEVEL_TOLERANCE = 2  # Z-Wave 0-99 levels (light brightness)

ZWAVE_JS_DOMAIN = "zwave_js"

ATTR_LAST_COMMAND = "last_command"
ATTR_LAST_DELIVERY = "last_delivery"
ATTR_LAST_VERIFY = "last_verify"
ATTR_MULTICAST_FAILURES = "multicast_failures"
