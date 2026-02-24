"""Shared test constants and XML fixtures."""

DEVICE_INFO_XML = """\
<?xml version="1.0" encoding="UTF-8" ?>
<device-info>
    <user-device-name>Living Room Roku</user-device-name>
    <model-name>Roku Ultra</model-name>
    <serial-number>ABC123XYZ</serial-number>
    <software-version>11.5.0</software-version>
    <device-id>DEVICE001</device-id>
</device-info>
"""

DEVICE_INFO_XML_MINIMAL = """\
<?xml version="1.0" encoding="UTF-8" ?>
<device-info>
    <model-name>Roku Express</model-name>
</device-info>
"""

APPS_XML = """\
<?xml version="1.0" encoding="UTF-8" ?>
<apps>
    <app id="12" type="appl" version="4.1">Netflix</app>
    <app id="13" type="appl" version="5.0">YouTube</app>
    <app id="14" type="appl" version="3.2">Hulu</app>
</apps>
"""

APPS_XML_EMPTY = """\
<?xml version="1.0" encoding="UTF-8" ?>
<apps>
</apps>
"""

SSDP_RESPONSE = (
    "HTTP/1.1 200 OK\r\n"
    "Cache-Control: max-age=3600\r\n"
    "ST: roku:ecp\r\n"
    "Location: http://192.168.1.100:8060/\r\n"
    "USN: uuid:roku:ecp:ABC123XYZ\r\n"
    "\r\n"
)

SSDP_RESPONSE_TWO = (
    "HTTP/1.1 200 OK\r\n"
    "Cache-Control: max-age=3600\r\n"
    "ST: roku:ecp\r\n"
    "Location: http://192.168.1.101:8060/\r\n"
    "USN: uuid:roku:ecp:DEF456ABC\r\n"
    "\r\n"
)
