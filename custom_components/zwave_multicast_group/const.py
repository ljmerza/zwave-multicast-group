"""Constants for Z-Wave Multicast Group."""

DOMAIN = "zwave_multicast_group"

CONF_ENTITIES = "entities"
CONF_TRAVEL_TIME = "travel_time"

DEFAULT_TRAVEL_TIME = 60  # seconds, end to end
MIN_TRAVEL_TIME = 5
MAX_TRAVEL_TIME = 600

# After the travel time, ask each multicast member for its real position and give the
# reports this long to arrive before deciding which ones missed the frame.
VERIFY_REPORT_WAIT = 3  # seconds
POSITION_TOLERANCE = 2  # percent

ZWAVE_JS_DOMAIN = "zwave_js"

ATTR_LAST_COMMAND = "last_command"
ATTR_LAST_DELIVERY = "last_delivery"
ATTR_LAST_VERIFY = "last_verify"
ATTR_MULTICAST_FAILURES = "multicast_failures"
