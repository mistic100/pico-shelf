import network
import socket
import ntptime
import time
import machine
import micropython
import json
import os
from time import sleep
from machine import Timer, Pin
from picozero import pico_led

micropython.alloc_emergency_exception_buf(100)

WIFI_FILE = 'wifi.json'
CONFIG_FILE = 'config.json'
WWW_DIR = 'www'
HEADER_OK = 'HTTP/1.0 200 OK\r\n\r\n'
HEADER_NOT_FOUND = 'HTTP/1.0 404 Object Not Found\r\n\r\n'

K_VALUE_OFF=1
K_VALUE_ON=0


k1 = Pin(10, mode=Pin.OUT, value=K_VALUE_OFF)
k2 = Pin(11, mode=Pin.OUT, value=K_VALUE_OFF)
k3 = Pin(12, mode=Pin.OUT, value=K_VALUE_OFF)
k4 = Pin(13, mode=Pin.OUT, value=K_VALUE_OFF)

btn1 = Pin(21, mode=Pin.IN, pull=Pin.PULL_UP)
btn2 = Pin(20, mode=Pin.IN, pull=Pin.PULL_UP)

timer = Timer()


state = False
schedule_state = False
override_state = False

lights = False
schedule_lights = False
override_lights = False

config = {}
wifi = {}


def load_config():
    global config
    global wifi
    
    try:
        f = open(WIFI_FILE, 'r')
        wifi = json.load(f)
        f.close()
    except OSError:
        print('MISSING wifi.json FILE!')
        quit()
    
    try:
        f = open(CONFIG_FILE, 'r')
        config = json.load(f)
        f.close()
        print("Loaded config: %s" %str(config))
    except OSError:
        print('MISSING config.json FILE!')
        quit()

def save_config():
    global config
    
    f = open(CONFIG_FILE, 'w')
    json.dump(config, f)
    f.close()
    print("Saved config: %s" %str(config))


def apply():
    global state
    global override_state
    global schedule_state
    global lights
    global override_lights
    global schedule_lights

    if state:
        k1.value(K_VALUE_ON if lights else K_VALUE_OFF)
        k2.value(K_VALUE_ON)
        k3.value(K_VALUE_ON)
        k4.value(K_VALUE_ON)

    else:
        k1.value(K_VALUE_OFF)
        k2.value(K_VALUE_OFF)
        k3.value(K_VALUE_OFF)
        k4.value(K_VALUE_OFF)

    override_state = state != schedule_state
    override_lights = lights != schedule_lights


def btn1_press(pin):
    global state

    state = not state
    apply()

def btn2_press(pin):
    global lights

    lights = not lights
    apply()
        
def timer_tick(t):
    global config
    global state
    global lights
    global override_state
    global schedule_state
    global override_lights
    global schedule_lights
    
    time = cet_time()

    c = config['week'] if time[6] <= 4 else config['weekend']
    schedule_state = time[3] >= c['from'] and time[3] < c['to']

    c = config['lights']
    schedule_lights = time[3] >= c['from'] and time[3] < c['to']
    
    if not override_state:
        state = schedule_state
    if not override_lights:
        lights = schedule_lights
    
    apply()
    

def connect_wifi():
    global wifi
    
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(wifi['ssid'], wifi['password'])

    while wlan.isconnected() == False:
        print('Waiting for connection...')
        sleep(1)

    ip = wlan.ifconfig()[0]
    print(f'IP: {ip}')
    return ip

def open_socket(ip):
    con = socket.socket()
    con.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    con.bind((ip, 80))
    con.listen(1)
    return con

def serve(con):
    while True:
        client = con.accept()[0]
        request = client.recv(1024)
        request = request.decode()
        print(request)

        try:
            headers, body = request.split('\r\n\r\n')
            headers = headers.split(' ')
            method = headers[0]
            path = headers[1]
            
            if path.startswith('/api'):
                serve_api(client, method, path.replace("/api", ""), body)
                continue
            
            if path == '/':
                path = '/index.html'

            f = open(WWW_DIR + path, 'r')
            content = f.read()
            f.close()
            client.sendall(HEADER_OK + content)

        except Exception as e:
            print(e)
            client.send(HEADER_NOT_FOUND)

        client.close()
        
def serve_api(client, method, path, body):
    global config
    global state
    global lights
    
    if (path == '' or path =='/') and method == 'GET':
        client.send(HEADER_OK + json.dumps({
            'time': cet_time(),
            'state': state,
            'lights': lights,
            'config': config
        }))
        
    elif path == '/state' and method == 'POST':
        state = body == 'true'
        apply()
        client.send(HEADER_OK)
        
    elif path == '/lights' and method == 'POST':
        lights = body == 'true'
        apply()
        client.send(HEADER_OK)
        
    elif path == '/config' and method == 'POST':
        config = json.loads(body)
        save_config()
        client.send(HEADER_OK)
    
    else:
        print(f'Invalid request {method} {path}')
        client.send(HEADER_NOT_FOUND)

    client.close()


def cet_time():
    year = time.localtime()[0]
    HHMarch = time.mktime((year,3 ,(31-(int(5*year/4+4))%7),1,0,0,0,0,0)) #Time of March change to CEST
    HHOctober = time.mktime((year,10,(31-(int(5*year/4+1))%7),1,0,0,0,0,0)) #Time of October change to CET
    now=time.time()
    if now < HHMarch :               # we are before last sunday of march
        cet=time.localtime(now+3600) # CET:  UTC+1H
    elif now < HHOctober :           # we are before last sunday of october
        cet=time.localtime(now+7200) # CEST: UTC+2H
    else:                            # we are after last sunday of october
        cet=time.localtime(now+3600) # CET:  UTC+1H
    return(cet)

def sync_time():
    ntptime.host = "fr.pool.ntp.org"
    ntptime.settime()
    print("UTC time: %s" %str(time.localtime()))
    print("CET time: %s" %str(cet_time()))

try:
    load_config()
    
    ip = connect_wifi()
    sync_time()
    
    pico_led.on()
    
    btn1.irq(trigger=Pin.IRQ_FALLING, handler=btn1_press)
    btn2.irq(trigger=Pin.IRQ_FALLING, handler=btn2_press)
    timer.init(period=1000, mode=Timer.PERIODIC, callback=timer_tick)
    
    con = open_socket(ip)
    serve(con)
    
    pico_led.off()
except KeyboardInterrupt:
    pico_led.off()
    machine.reset()
