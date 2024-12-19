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
import socket
import time

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
frame_dict = {}

# HTML template for the webpage
def webpage(request, writer, *values):
    global frame_dict
    # Send the HTTP response
    writer.write('HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n')
    writer.write(str(f"""<!DOCTYPE html>
            <html>
                <head>
                    <title>PicoW BLE -> MQTT</title>
                    <meta charset="UTF-8">
                </head>
                <body>
                    <div>
                        <p><a href="/reset">Click to reset the PicoW</a></p>
                    </div>
                    <div>
                        <h1>List of devices seen by PicoW ({len(list(frame_dict.keys()))}):</h1>
                        <table>
                            <thead>
                                <tr>
                                    <th>addr</th>
                                    <th>rssi</th>
                                    <th>raw_data</th>
                                    <th>data</th>
                                    <th>timestamp</th>
                                    <th>to_send</th>
                                </tr>
                            </thead>
                            <tbody>"""))

    for curr_addr, curr_frame in frame_dict.items():
        curr_data = {}
        if 'data' in curr_frame.keys():
            curr_data = curr_frame['data']

        curr_to_send = 'N'
        if curr_frame['to_send']:
            curr_to_send = 'Y'

        writer.write(str(f"""   <tr>
                                    <td>{curr_addr}</td>
                                    <td>{curr_frame['rssi']}</td>
                                    <td>{curr_frame['raw_data']}</td>
                                    <td>{json.dumps(curr_data)}</td>
                                    <td>{curr_frame['timestamp']}</td>
                                    <td>{curr_to_send}</td>
                                <tr>"""))

    writer.write(str(f"""   </tbody>
                        </table>
                    </div>
                </body>
            </html>"""))
    

# Asynchronous function to handle client's requests
async def handle_client(reader, writer):
    print("Client connected")
    request_line = await reader.readline()
    print('Request:', request_line)
    
    # Skip HTTP request headers
    while await reader.readline() != b"\r\n":
        pass
    
    request = str(request_line, 'utf-8').split()[1]
    print('Request:', request)
    
    # Process the requests
    if request == '/reset':
        soft_reset()

    # Generate HTML response
    webpage(request, writer)  

    # Close the connection
    await writer.drain()
    await writer.wait_closed()
    print('Client Disconnected')

# Respond to connectivity being (re)established
async def up(client):
    while True:
        await client.up.wait()  # Wait on an Event
        client.up.clear()

# Get BLE frames from scanner
async def get_ble_adv():
    global frame_dict
    while True:
        async with aioble.scan(1000, interval_us=30000, window_us=30000) as scanner:
            async for result in scanner:
                # ['__class__', '__init__', '__module__', '__qualname__', '__str__', '__dict__', 'adv_data', 'connectable', 'name',
                #  'resp_data', 'rssi', '_decode_field', '_update', 'device', 'manufacturer', 'services']
                if result.adv_data:
                    raw_adv = ''.join('%02x' % struct.unpack("B", bytes([x]))[0] for x in result.adv_data)
                    dec_adv = decode_ble(raw_adv)
                    
                    dict_result = {}
                    dict_result['to_send'] = True
                    dict_result['addr'] = result.device.addr_hex()
                    dict_result['rssi'] = result.rssi
                    dict_result['timestamp'] = time.time()
                    
                    if result.name():
                        dict_result['name'] = result.name()
                    dict_result['raw_data'] = raw_adv
                    if dec_adv:
                        dict_result['data'] = dec_adv

                    frame_dict[result.device.addr_hex()] = dict_result

# Network starting and OTA update
async def init(client):
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

# MQTT client and local Webserver
async def main(client):
    global frame_dict
    print ("Connecting to MQTT")
    await client.connect()
    print ("Connected")
    asyncio.create_task(up(client))
    asyncio.create_task(get_ble_adv())

    # Watchdog timer
    global wdt
    wdt = WDT(timeout=8388)
    
    # Start the server and run the event loop
    print('Setting up server')
    server = asyncio.start_server(handle_client, "0.0.0.0", 80)
    asyncio.create_task(server)

    print('All up and running!')
    while True:
        for curr_addr, curr_result in frame_dict.items():
            if curr_result['to_send']:
                # Send to MQTT Broker
                curr_result.pop('to_send')
                await client.publish(f'ble_{curr_addr}/', json.dumps(curr_result), qos = 1)
                
                # Print to console
                #print(json.dumps(curr_result))

                # Set device flag to Flase
                frame_dict[curr_addr]['to_send'] = False
        
        wdt.feed()
        await asyncio.sleep(0.5)

# MAIN #
if __name__ == "__main__":
    try:
        asyncio.run(init(client))
        loop = asyncio.get_event_loop()
        loop.create_task(main(client))
        loop.run_forever()
    except Exception as e:
        print(e)
        soft_reset() 
    finally:
        client.close()
        exit(0)
