def decode_ble(pkg):
    output = {}
        
    # LYWSD03MMC ATC1441
    if pkg[4:8] == '1a18':
        output['temp'] = int(pkg[20:24], 16) / 10.0
        output['hum'] = int(pkg[24:26], 16)
        output['batt'] = int(pkg[26:28], 16)
        output['battery_volts'] = int(pkg[28:32], 16) / 10.0
        output['counter'] = int(pkg[32:34], 16)
    
    # LYWSD03MMC ATC1441 + AdFlags
    elif pkg[10:14] == '1a18':
        output['temp'] = int(pkg[26:30], 16) / 10
        output['hum'] = int(pkg[30:32], 16)
        output['batt'] = int(pkg[32:34], 16)
        output['battery_volts'] = int(pkg[34:38], 16)
        output['counter'] = int(pkg[38:40], 16)
        
    return output
