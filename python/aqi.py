#!/usr/bin/python -u
# coding=utf-8
# "DATASHEET": http://cl.ly/ekot
# https://gist.github.com/kadamski/92653913a53baf9dd1a8
from __future__ import print_function

import json
import serial
import struct
import subprocess
import time

DEBUG = 0
CMD_MODE = 2
CMD_QUERY_DATA = 4
CMD_DEVICE_ID = 5
CMD_SLEEP = 6
CMD_FIRMWARE = 7
CMD_WORKING_PERIOD = 8
MODE_ACTIVE = 0
MODE_QUERY = 1
PERIOD_CONTINUOUS = 0

JSON_FILE = '/var/www/html/aqi.json'
JSON_FILE_OUTDOOR = '/var/www/html/aqi_outdoor.json'

MQTT_HOST = ''
MQTT_TOPIC = '/weather/particulatematter'



#byte, data = 0, ""

def dump(d, prefix=''):
    print(prefix + ' '.join(x.encode('hex') for x in d))


def construct_command(cmd, data=None):
    if data is None:
        data = []
    assert len(data) <= 12
    data += [0, ] * (12 - len(data))
    checksum = (sum(data) + cmd - 2) % 256
    ret = "\xaa\xb4" + chr(cmd)
    ret += ''.join(chr(x) for x in data)
    ret += "\xff\xff" + chr(checksum) + "\xab"

    if DEBUG:
        dump(ret, '> ')
    return ret


def process_data(d):
    r = struct.unpack('<HHxxBB', d[2:])
    pm25 = r[0] / 10.0
    pm10 = r[1] / 10.0
    checksum = sum(ord(v) for v in d[2:8]) % 256
    return [pm25, pm10]
    # print("PM 2.5: {} μg/m^3  PM 10: {} μg/m^3 CRC={}".format(pm25, pm10, "OK" if (checksum==r[2] and r[3]==0xab) else "NOK"))


def process_version(d):
    r = struct.unpack('<BBBHBB', d[3:])
    checksum = sum(ord(v) for v in d[2:8]) % 256
    print("Y: {}, M: {}, D: {}, ID: {}, CRC={}".format(r[0], r[1], r[2], hex(r[3]), "OK" if (
                checksum == r[4] and r[5] == 0xab) else "NOK"))


def read_response(ser):
    byte = 0
    while byte != "\xaa":
        byte = ser.read(size=1)

    d = ser.read(size=9)

    if DEBUG:
        dump(d, '< ')
    return byte + d


def cmd_set_mode(ser, mode=MODE_QUERY):
    ser.write(construct_command(CMD_MODE, [0x1, mode]))
    read_response(ser)


def cmd_query_data(ser):
    ser.write(construct_command(CMD_QUERY_DATA))
    d = read_response(ser)
    vals = []
    if d[1] == "\xc0":
        vals = process_data(d)
    return vals


def cmd_set_sleep(ser, sleep):
    mode = 0 if sleep else 1
    ser.write(construct_command(CMD_SLEEP, [0x1, mode]))
    read_response(ser)


def cmd_set_working_period(ser, period):
    ser.write(construct_command(CMD_WORKING_PERIOD, [0x1, period]))
    read_response(ser)


def cmd_firmware_ver(ser):
    ser.write(construct_command(CMD_FIRMWARE))
    d = read_response(ser)
    process_version(d)


def cmd_set_id(ser, id):
    id_h = (id >> 8) % 256
    id_l = id % 256
    ser.write(construct_command(CMD_DEVICE_ID, [0] * 10 + [id_l, id_h]))
    read_response(ser)


def pub_mqtt(jsonrow):
    cmd = ['mosquitto_pub', '-h', MQTT_HOST, '-t', MQTT_TOPIC, '-s']
    print('Publishing using:', cmd)
    with subprocess.Popen(cmd, shell=False, bufsize=0, stdin=subprocess.PIPE).stdin as f:
        json.dump(jsonrow, f)


def do_the_stuff(ser, json_file):
    sensor_name = "Indoor Sensor" if ser == serial_indoor else "Outdoor Sensor"
    cmd_set_sleep(ser, 0)
    for t in range(15):
        values = cmd_query_data(ser)
        print("loop", values)
        if values is not None and len(values) == 2:
            print(sensor_name, ": PM2.5: ", values[0], ", PM10: ", values[1])
            time.sleep(2)
    # open stored data
    try:
        with open(json_file) as json_data:
            data = json.load(json_data)
    except IOError as e:
        data = []
    # check if length is more than 100 and delete first element
    # if len(data) > 100:
    #    data.pop(0)
    # append new values
    jsonrow = {'pm25': values[0], 'pm10': values[1], 'time': time.strftime("%H:%M:%S %m/%d/%Y %Z")}
    data.append(jsonrow)
    # save it
    with open(json_file, 'w') as outfile:
        json.dump(data, outfile)
    if MQTT_HOST != '':
        pub_mqtt(jsonrow)
    cmd_set_sleep(ser, 1)


serial_indoor = serial.Serial()
serial_indoor.port = "/dev/ttyUSB0"
serial_indoor.baudrate = 9600
serial_indoor.open()
serial_indoor.flushInput()

serial_outdoor = serial.Serial()
serial_outdoor.port = "/dev/ttyUSB1"
serial_outdoor.baudrate = 9600
serial_outdoor.open()
serial_outdoor.flushInput()

cmd_set_sleep(serial_indoor, 0)
cmd_set_sleep(serial_outdoor, 0)
cmd_firmware_ver(serial_indoor)
cmd_firmware_ver(serial_outdoor)
cmd_set_working_period(serial_indoor, PERIOD_CONTINUOUS)
cmd_set_working_period(serial_outdoor, PERIOD_CONTINUOUS)
cmd_set_mode(serial_indoor, MODE_QUERY)
cmd_set_mode(serial_outdoor, MODE_QUERY)

if __name__ == "__main__":
    while True:
        print("looped Sleeping")
        do_the_stuff(serial_indoor, JSON_FILE)
        do_the_stuff(serial_outdoor, JSON_FILE_OUTDOOR)
        sleep_time = 10
        mins = sleep_time / 60
        print("Putting sensors to sleep for ", mins, " minutes...")
        time.sleep(sleep_time)
        print("Done Sleeping")
