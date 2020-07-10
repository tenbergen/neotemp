#!/usr/bin env python3
# /etc/init.d/neotemp.py
### BEGIN INIT INFO
# Provides:		neotmep.py
# Required-Start:	$remote_fs $syslog
# Required-Stop:	$remote_fs $syslog
# Default-Start:	2 3 4 5
# Default-Stop:		0 1 6
# Short-Description:	Daemon which turns a 25-LED NeoPixel strip into a thermometer at boot time.
# Description:		Enable service provided by daemon.
### END INIT INFO
import board, neopixel
import re, random, colorsys, threading, atexit, json
import urllib.request, datetime, os.path
from time import sleep

# NeoPixel Setup
neopixel_pin = board.D21  # Set to where DATA line is connected. Default is GPIO 18.
neopixel_length = 32  # Set to how many lights there are on the NeoPixel strand.
brightness = 0.1  # Set how bright in the range [0..1] the NeoPixels shall be.

# Offset correction
# Needed because pixels will likely not be an exact match to degree indicators on your bezel.
lower_bound = 90  # Correct temperatures below this value...
lower_corr = -1  # ... by this many pixels (zero for no correction).
upper_bound = 115  # Correct temperatures above this value...
upper_corr = 1  # ... by this many pixels (zero for no correction).

# Color Setup - adjust colors to your preference by setting 'off' to whatever you want. Black recommended.
# Note: The more white they are and the more pixels are lit, the more current it draws,
# so make sure your power supply provides at least 3amps to your pixels.
black = (0, 0, 0)
white = (255, 255, 255)
magenta = (255, 0, 255)
red = (255, 0, 0)
yellow = (255, 255, 0)
green = (0, 255, 0)
cyan = (0, 255, 255)
blue = (0, 0, 255)
off = black  # used for "inactive" pixels, i.e., pixels that aren't lit given current temperature
dim = (64, 64, 64)  # used for chase animation
dimmest = (17, 17, 17)  # used for chase animation
on = white  # used for "active" pixels, if you don't want color coding temperature.

# Location Setup - needed to determine the outside temperature where you are
city = "Oswego"
region = "USA"

###
### From here, don't touch, or you might break stuff.
###
DEBUG = False  # Debug mode makes temperature switch a lot.
INTERACTIVE = False  # Ask for user input to set color during debug.

# Global infrastructure. Don't touch.
neotempThread = threading.Thread()
lock = threading.Lock()
pixels = neopixel.NeoPixel(neopixel_pin, neopixel_length, brightness=brightness, pixel_order=neopixel.GRB)
weather_srvc = "http://wttr.in/"  # This is the weather service we're polling. See: http://wttr.in/:help
weather_opts = "?format=%t"  # Single-line output preferred, so we can parse the temperature integer later.
url = weather_srvc + city + "," + region + weather_opts  # This is the URL for the weather near YOU.
interval = 1800  # don't poll the weather service more often than once every 30secs. They might not like that.
timeout  = 0.01  # Transition timing for animations.
if DEBUG and INTERACTIVE:
    interval = 0
elif DEBUG:
    interval = 3
hueGPIOThread= threading.Thread()
FILEMODE     = False
FILENAME     = "/path/to/hueGPIO.json"
filedate     = datetime.datetime.now()

## Temperature Setup - all temperatures in Fahrenheit because, let's be honest:
## unit-aware computing makes imperial temperature scales less annoying. Also, it maps better to a human perceivable range.
## See: https://xkcd.com/1643/
# Minimum and maximum temperatures to consider for lighting the pixels. Used to map integer ranges.
temp_min = -40
temp_max = 140
# Minimum and maximum hue value to consider for temperatures to display.
# Idea: the colder the temp, the more blue, so the hue value should be closer to 255;
#       the warmer the temp, the more red,  so the hue value should be closer to 0.
# This will transition from purple (intolerable, ca. -40 degF ... or degC ... doesn't matter) over blue
# (terribly cold, ca. 10 deg F / -32 deg C), # cyan (freezing, ca. 32 degF / 0 degC), green (chilly, 45 degF / 7 degC),
# yellow (comfortable 70 degF / 22 degC), orange (pleasant, ca. 80 degF / 25 degC) , to red (uncomfortable 90 degF / 32 degC and up)
# But, hue scale is inverted compared to temperature, so, we invert min/max.
hue_min = 104
hue_max = 0
# Minimum and maximum temperature to compute hue. This is needed to prevent colors for temperatures stop "looking" colder or hotter
# Idea: everything below freezing (32 degF / 0 degC) will stay blue-ish,
#       everything above terribly hot (90 degF / 32 degC) will stay red.
# Caveat: temperatures incompatible with life will be purple. Let's hope you won't see that.
display_min = 32
display_max = 90
# Helper variables needed to keep track of what temperature is being displayed.
curTemp = temp_min
preTemp = curTemp

# Helper function to make neat transition animations. Also turns off previous warmer pixels, if needed.
def transition(target, color):
    global pixels
    if preTemp <= curTemp:  # it's getting warmer, so run up the LEDs
        for n in range(target):
            pixels[n] = color
            sleep(timeout)
        for n in range(neopixel_length - target):
            pixels[n + target] = off
            sleep(timeout)
    if preTemp > curTemp:  # it's getting colder, so run down the LEDs
        for n in reversed(range(neopixel_length - target)):
            pixels[n + target] = off
            sleep(timeout)
        for n in reversed(range(target)):
            pixels[n] = color
            sleep(timeout)


# Interrupt handler that turns pixels off when neotemp exits (SIGTERM). Also unschedules the next thread.
def interrupt():
    global neotempThread
    global pixels
    neotempThread.cancel()
    sleep(1)
    pixels.fill(black)

# Interface function to allow hueGPIO to control "off"
def setHueColor(color, bright):
    global off, brightness
    global neotempThread
    neotempThread.cancel()
    off = int(color[0]), int(color[1]), int(color[2])
    brightness = bright
    if brightness == 0.0:
        off = black
    else:
        pixels.brightness = brightness
    # pixels.fill(off)
    neotempThread = threading.Timer(0, run, ())
    neotempThread.start()
    if DEBUG:
        print("New color received from hueGPIO: ", off, ", brightness: ", brightness)


# Interface function to read hueGPIO color changes from json file and control "off"
def loadHueColor():
    global filedate, hueGPIOThread
    if os.path.isfile(FILENAME):
        with open(FILENAME) as json_file:
            modTime = datetime.datetime.fromtimestamp(os.path.getmtime(FILENAME))
            if modTime > filedate:
                filedate = modTime
                data = json.load(json_file)
                color = int(data['color'].split(',')[0]), int(data['color'].split(',')[1]), int(data['color'].split(',')[2])
                bright = float(data['brightness'])
                setHueColor(color, bright)
    hueGPIOThread = threading.Timer(1, loadHueColor, ())
    hueGPIOThread.start()


# Initializes the pixels at startup. Turns them all on and off in a neat animation, partly because we can and partly
# to test if they are all working.
def initPixels():
    global neotempThread
    global pixels
    pixels.fill(off)
    sleep(0.5)
    for n in range(neopixel_length):
        sleep(timeout)
        pixels[n] = on
        if n == 0:
            continue
        pixels[n - 1] = dim
        if n == 1:
            continue
        pixels[n - 2] = dimmest
        if n == 2:
            continue
        pixels[n - 3] = off
    for n in reversed(range(neopixel_length)):
        sleep(timeout)
        pixels[n] = on
        if n == neopixel_length - 1:
            continue
        pixels[n + 1] = dim
        if n == neopixel_length - 2:
            continue
        pixels[n + 2] = dimmest
        if n == neopixel_length - 3:
            continue
        pixels[n + 3] = off
    if neopixel_length > 2:
        pixels[0] = dim
        pixels[1] = dimmest
        pixels[2] = off
        sleep(timeout)
        pixels[0] = dimmest
        pixels[1] = off
        sleep(timeout)
        pixels[0] = off
    sleep(0.5)

    # Create neotemp thread, start immediately
    neotempThread = threading.Timer(0, run, ())
    neotempThread.start()
    if FILEMODE:
        hueGPIOThread = threading.Timer(0, loadHueColor, ())
        hueGPIOThread.start()


# Main program, which determines the current temperature and lights the pixels.
# Threading allows us to avoid while(true) loops.
def run():
    global curTemp, preTemp
    global interval
    global neotempThread
    if DEBUG:
        curTemp = random.randrange(temp_min, temp_max)
        if INTERACTIVE:
            curTemp = int(input("Next temperature:"))
    else:
        try:
            # get current weather for current location and extract temperature
            response = urllib.request.urlopen(urllib.request.Request(url))
            curTemp = int(re.sub("[^\d.]", "", response.read().decode('utf-8')))
        except:
            # if this doesn't work, the weather service probably didn't like the scheduled request.
            # Try again soon-ish, doesn't matter when.
            interval = random.randrange(0, temp_max)
            curTemp = preTemp

    # compute which pixels to light in the interval [0..neopixel_length]
    # all pixels up to targetPixel will be toggled "active"
    targetPixel = round((curTemp - temp_min) * (neopixel_length - 0) / (temp_max - temp_min) + 0)
    # pixels and temperature "ticks" on your gauge might not line up. Correct the pixels as follows.
    if curTemp <= lower_bound:
        targetPixel = targetPixel + lower_corr
    if curTemp >= upper_bound:
        targetPixel = targetPixel + upper_corr
    # if targetPixel exceeds number of pixels, fix it.
    if targetPixel < 0:
        targetPixel = 0
    if targetPixel > neopixel_length:
        targetPixel = neopixel_length

    # compute the color of the "active" pixels. Very cold and very hot temperatures turn purple.
    targetHue = hue_min + ((hue_max - hue_min) / (display_max - display_min)) * (curTemp - display_min)
    # limit extremely hot temperatures to "red."
    if targetHue < 0:
        targetHue = 0
    # limit extremely cold temperatures to "blue."
    if targetHue > display_max:
        targetHue = display_max
    # convert hue to RBG, because hue is convenient for integer mapping, but pixels are addressed with RBG.
    (r, g, b) = colorsys.hls_to_rgb(((targetHue) / 255), 0.5, 1)
    # green channel is wide, so let's make it smaller to get colors that visually map better to temperatures
    rgb = (int(r * 255), int(g * 64), int(b * 255))

    if DEBUG:
        print(datetime.now(), ": ", curTemp, ", hue: ", round(targetHue), ", ", rgb, "for pixel ", targetPixel)

    # now turn appropriate pixels active and inactive
    transition(targetPixel, rgb)

    # remember what temperature you displayed last (to switch of unnecessary pixels, possibly)
    preTemp = curTemp
    # recursively schedule next thread
    neotempThread = threading.Timer(interval, run, ())
    neotempThread.start()


# start neotemp
initPixels()
# when neocal exits (SIGTERM), unschedule the next thread
atexit.register(interrupt)
# END.
