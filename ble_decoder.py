def decode_ble(pkg):
    output = {}
    
    try:
        # LYWSD03MMC
        if pkg[4:8] == '1a18' or pkg[10:14] == '1a18':
            pkg_init = pkg.index('1a18') + 4 # Support for AdFlags

            # ATC1441
            if pkg_init + 26 == len(pkg):
                output['temp'] = int(pkg[12+pkg_init:16+pkg_init], 16) / 10.0
                output['hum'] = int(pkg[16+pkg_init:18+pkg_init], 16)
                output['batt'] = int(pkg[18+pkg_init:20+pkg_init], 16)
                output['battery_volts'] = int(pkg[20+pkg_init:24+pkg_init], 16)
                output['counter'] = int(pkg[24+pkg_init:26+pkg_init], 16)

            # PVVX
            else:
                temp_little = pkg[12+pkg_init:16+pkg_init]
                temp_big = ''.join([temp_little[i:i+2] for i in range(0, len(temp_little), 2)][::-1])
                output['temp'] = int(temp_big, 16) / 100.0
                
                hum_little = pkg[16+pkg_init:20+pkg_init]
                hum_big = ''.join([hum_little[i:i+2] for i in range(0, len(hum_little), 2)][::-1])
                output['hum'] = int(hum_big, 16) / 100.0

                vbat_little = pkg[20+pkg_init:24+pkg_init]
                vbat_big = ''.join([vbat_little[i:i+2] for i in range(0, len(vbat_little), 2)][::-1])
                output['battery_volts'] = int(vbat_big, 16)

                output['batt'] = int(pkg[24+pkg_init:26+pkg_init], 16) 
                output['counter'] = int(pkg[26+pkg_init:28+pkg_init], 16)
                output['flag'] = int(pkg[28+pkg_init:30+pkg_init], 16)
    
    except Exception as e:
        output = {}
        print(e)
    
    finally:
        return output
