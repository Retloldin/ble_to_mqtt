import aioble
import json
from mqtt_as import MQTTClient, config
import struct
import uasyncio as asyncio
import ntptime
from machine import WDT, soft_reset
from ble_decoder import decode_ble
from ota import OTAUpdater
from sys import exit

# Config file
try:
    with open('/params.json', 'rb') as f:
        params = json.load(f)
except OSError:
    print('Config file not found!')
    exit(0)
        
# MQTT config
config['ssid'] = params['ssid']
config['wifi_pw'] = params['wifi_pw']
config['server'] = params['server']
config['port'] = params['port']
config['user'] = params['user']
config['password'] = params['password']
config["queue_len"] = 1

# (Optional) Enable SSL/TLS support for the MQTT client
# import ssl
# Let's Encrypt Authority
# ca_certificate_path = "/certs/isrgrootx1.der"
# print('Loading CA Certificate')
# with open(ca_certificate_path, 'rb') as f:
#     cacert = f.read()
# print('Obtained CA Certificate')
# config['ssl'] = True
# config['ssl_params'] = {'server_hostname': 'mqtt.internal.local', 'cadata': cacert, 'cert_reqs': ssl.CERT_REQUIRED}

client = MQTTClient(config)
wdt = None

async def up(client):  # Respond to connectivity being (re)established
    while True:
        await client.up.wait()  # Wait on an Event
        client.up.clear()

async def get_ble_adv():
    ble_frame = []
    async with aioble.scan(1000) as scanner:
        async for result in scanner:
            # ['__class__', '__init__', '__module__', '__qualname__', '__str__', '__dict__', 'adv_data', 'connectable', 'name',
            #  'resp_data', 'rssi', '_decode_field', '_update', 'device', 'manufacturer', 'services']
            if result.adv_data:
                raw_adv = ''.join('%02x' % struct.unpack("B", bytes([x]))[0] for x in result.adv_data)
                dec_adv = decode_ble(raw_adv)
                
                dict_result = {}
                dict_result['addr'] = result.device.addr_hex()
                dict_result['rssi'] = result.rssi
                if result.name():
                    dict_result['name'] = result.name()
                dict_result['raw_data'] = raw_adv
                if dec_adv:
                    dict_result['data'] = dec_adv
                
                ble_frame.append(dict_result)

    return ble_frame

async def main(client):
    global params
    print ("Connecting to WiFi")
    await client.wifi_connect()
    print ("Updating system time")
    ntptime.host = params['ntp_host']
    ntptime.timeout = 10
    ntptime.settime()
    print ("Checking for OTA Update")
    firmware_url = f"https://github.com/{params['GitHub_username']}/{params['repo_name']}/{params['branch']}/"
    ota_updater = OTAUpdater(firmware_url, 'main.py', 'ble_decoder.py')
    ota_updater.download_and_install_update_if_available()
    print ("Connecting to MQTT")
    await client.connect()
    print ("Connected")
    asyncio.create_task(up(client))

    # Watchdog timer
    global wdt
    wdt = WDT(timeout=8388)

    while True:
        result_frame = await get_ble_adv()
        if result_frame:
            for result in result_frame:
                await client.publish(f'ble/{result["addr"]}', json.dumps(result), qos = 1)
                #print(json.dumps(result))
        wdt.feed()

try:
    asyncio.run(main(client))
except Exception as e:
    soft_reset() 
finally:
    client.close()
    exit(0)
