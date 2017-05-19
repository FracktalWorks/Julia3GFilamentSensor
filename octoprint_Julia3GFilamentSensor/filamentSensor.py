import RPi.GPIO as GPIO
import time

#GPIO.setmode(GPIO.BCM)
latestPulse={}
filamentRunoutTime=15
def enable(encoderPin):
	GPIO.setup(encoderPin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
	GPIO.add_event_detect(encoderPin, GPIO.RISING, callback=callback, bouncetime=300)
	latestPulse = time.time()

def dissable(encoderPin):
	GPIO.remove_event_detect(encoderPin)

def callback(channel):
	latestPulse[channel[0]] = time.time()
	print channel,latestPulse[channel[0]]
def isRotating(sensorPin):
	'If the encoder hasnt moved for some time, means the fiament sensor isnt rotating'
	if (time.time() - latestPulse[sensorPin] > filamentRunoutTime):
		return False
	else:
		return True
def getStatus(sensorPin):
	return {'lastEncoderStep': time.time() - latestPulse[sensorPin],'isRotating': isRotating(sensorPin)}
enable(5)
enable(6)

if __name__ == '__main__':
	while True:
		pass
