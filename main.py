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

# Globals
frame_dict = {}
log_list = []
start_time = 0

# Logging (50 rows max)
def logging(_str, func_name='unknown', severity='INFO', _print=True):
    global log_list

    if _print:
        print(f'{time.time()} | {severity} | {func_name} | {_str}')

    if len(log_list) == 50:
        log_list.pop(0)
    log_list.append(f'{time.time()} | {severity} | {func_name} | {_str}')

# HTML template for the webpage
async def webpage(request, writer, *_values):
    global frame_dict
    global log_list
    global start_time

    # PicoW uptime to text
    curr_uptime = time.time() - start_time
    _hours = curr_uptime // 3600
    _minutes = (curr_uptime % 3600) // 60
    _seconds = curr_uptime % 60
    _uptime = '{:02}:{:02}:{:02}'.format(_hours, _minutes, _seconds)
    
    writer.write('HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n')
    writer.write(str(f"""<!DOCTYPE html>
            <html>
                <head>
                    <title>PicoW BLE -> MQTT</title>
                    <meta charset="UTF-8">
                </head>
                <body>
                    <div>
                        <p>PicoW BLE -> MQTT (Uptime {_uptime})</p>
                        <p style='position: fixed; top: 0px !important; right: 1em !important;'><a href="/reset">Click to reset the PicoW</a></p>
                    </div>"""))
    await writer.drain()


    if request == '/pending':
        writer.write(str(f"""
                    <div>
                        <p><a href="/">Back</a></p>
                        <h1>List of devices pending to send (Total seen: {len(list(frame_dict.keys()))})</h1>
                        <table>
                            <thead>
                                <tr>
                                    <th>addr</th>
                                    <th>rssi</th>
                                    <th>raw_data</th>
                                    <th>data</th>
                                    <th>timestamp</th>
                                </tr>
                            </thead>
                            <tbody>"""))

        for curr_addr, curr_frame in frame_dict.items():
            if curr_frame:
                curr_data = {}
                if 'data' in curr_frame.keys():
                    curr_data = curr_frame['data']

                writer.write(str(f"""   
                                <tr>
                                    <td>{curr_addr}</td>
                                    <td>{curr_frame['rssi']}</td>
                                    <td>{curr_frame['raw_data']}</td>
                                    <td>{json.dumps(curr_data)}</td>
                                    <td>{curr_frame['timestamp']}</td>
                                <tr>"""))
                await writer.drain()

        writer.write(str(f"""</tbody>
                        </table>
                    </div>"""))

    elif request == '/log':
        writer.write(str(f"""
                    <div>
                        <p><a href="/">Back</a></p>
                        <h1>Logs:</h1>"""))

        for curr_log in log_list:
            writer.write(str(f"""<p>{curr_log}</p>"""))
            await writer.drain()

        writer.write(str(f"""</div>"""))

    elif request == '/reset':
        writer.write(str(f"""
                    <div>
                        <h1>Do you want to reboot the PicoW?</h1>
                        <p><a href="/reset_confirm">YES</a>&emsp;<a href="/">NO</a></p>
                    </div>"""))

    # Default page
    else:
        pending_total = 0
        for curr_addr, curr_frame in frame_dict.items():
            if curr_frame:
                pending_total += 1

        writer.write(str(f"""
                    <div>
                        <p>Total devices seen by PicoW: {len(list(frame_dict.keys()))} <a href="/pending">Pending list ({pending_total})</a></p>
                        <p>{len(log_list)} lines saved in log <a href="/log">See logs</a></p>
                    </div>"""))

    writer.write(str(f"""
                </body>
            </html>"""))
    await writer.drain()
    

# Asynchronous function to handle client's requests
async def handle_client(reader, writer):
    #logging("Client connected", 'handle_client()', 'DEBUG')
    request_line = await reader.readline()
    
    # Skip HTTP request headers
    while await reader.readline() != b"\r\n":
        pass
    
    request = str(request_line, 'utf-8').split()[1]
    #logging(f'Request: {request}', 'handle_client()', 'DEBUG')
    
    # Process the special requests
    if request == '/reset_confirm':
        soft_reset()

    # Generate HTML response and send the response
    await webpage(request, writer)  

    # Close the connection
    await writer.drain()
    await writer.wait_closed()
    #logging("Client disconnected", 'handle_client()', 'DEBUG')

# Respond to connectivity being (re)established
async def up(client):
    while True:
        await client.up.wait()  # Wait on an Event
        client.up.clear()

# Get BLE frames from scanner
async def get_ble_adv():
    global frame_dict
    while True:
        try:
            async with aioble.scan(1000, interval_us=30000, window_us=30000) as scanner:
                async for result in scanner:
                    # ['__class__', '__init__', '__module__', '__qualname__', '__str__', '__dict__', 'adv_data', 'connectable', 'name',
                    #  'resp_data', 'rssi', '_decode_field', '_update', 'device', 'manufacturer', 'services']
                    if result.adv_data:
                        raw_adv = ''.join('%02x' % struct.unpack("B", bytes([x]))[0] for x in result.adv_data)
                        dec_adv = decode_ble(raw_adv)
                        
                        dict_result = {}
                        dict_result['addr'] = result.device.addr_hex()
                        dict_result['rssi'] = result.rssi
                        dict_result['timestamp'] = time.time()

                        if result.name():
                            dict_result['name'] = result.name()
                        dict_result['raw_data'] = raw_adv
                        if dec_adv:
                            dict_result['data'] = dec_adv

                        frame_dict[result.device.addr_hex()] = dict_result

        except Exception as e:
            logging(e, 'get_ble_adv()', 'ERROR')

# Network starting and OTA update
async def init(client):
    global params
    logging("Connecting to WiFi", 'init()')
    await client.wifi_connect()
    logging("Updating system time", 'init()')
    ntptime.host = params['ntp_host']
    ntptime.timeout = 10
    ntptime.settime()
    logging("Checking for OTA Update", 'init()')
    firmware_url = f"https://github.com/{params['GitHub_username']}/{params['repo_name']}/{params['branch']}/"
    ota_updater = OTAUpdater(firmware_url, 'main.py', 'ble_decoder.py')
    ota_updater.download_and_install_update_if_available()

# MQTT client and local Webserver
async def main(client):
    global frame_dict

    # Connect to MQTT
    logging("Connecting to MQTT", 'main()')
    await client.connect()
    logging("Connected", 'main()')
    asyncio.create_task(up(client))

    # Start the BLE scanner
    asyncio.create_task(get_ble_adv())
    
    # Start the webserver on port 80
    logging('Setting up server', 'main()')
    server = asyncio.start_server(handle_client, "0.0.0.0", 80)
    asyncio.create_task(server)

    global start_time
    start_time = time.time()
    logging('All up and running!', 'main()')

    # Watchdog timer
    wdt = WDT(timeout=8388)

    while True:
        try:
            for curr_addr, curr_result in frame_dict.items():
                if curr_result:
                    # Send to MQTT Broker
                    await client.publish(f'ble_{curr_addr}/', json.dumps(curr_result), qos = 1)
                    
                    # Print to console
                    #print(json.dumps(curr_result))

                    # Set device frame data to None
                    frame_dict[curr_addr] = None

        except Exception as e:
            logging(e, 'main()', 'ERROR')
        
        wdt.feed()
        await asyncio.sleep(0.5)

# MAIN #
if __name__ == "__main__":
    try:
        client = MQTTClient(config)
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
