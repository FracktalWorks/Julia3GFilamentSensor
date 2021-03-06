# coding=utf-8
from __future__ import absolute_import

import octoprint.plugin
from octoprint.events import eventManager, Events
from flask import jsonify, make_response, request
import RPi.GPIO as GPIO
import time
from threading import Timer

# TODO:
'''
API to change settings, and pins
API to Caliberate
API to enable/Dissable sensor, and save this information
'''


class RepeatedTimer(object):
	def __init__(self, interval, function, *args, **kwargs):
		self._timer = None
		self.interval = interval
		self.function = function
		self.args = args
		self.kwargs = kwargs
		self.is_running = False

	def _run(self):
		self.is_running = False
		self.start()
		self.function(*self.args, **self.kwargs)

	def start(self):
		if not self.is_running:
			self._timer = Timer(self.interval, self._run)
			self._timer.start()
			self.is_running = True

	def stop(self):
		if self.is_running:
			self._timer.cancel()
			self.is_running = False


class Julia3GFilamentSensor(octoprint.plugin.StartupPlugin,
							octoprint.plugin.EventHandlerPlugin,
							octoprint.plugin.SettingsPlugin,
							octoprint.plugin.TemplatePlugin,
							octoprint.plugin.BlueprintPlugin):
	def initialize(self):
		'''
        Checks RPI.GPIO version
        Initialises board
        :return: None
        '''
		self._logger.info("Running RPi.GPIO version '{0}'".format(GPIO.VERSION))
		if GPIO.VERSION < "0.6":  # Need at least 0.6 for edge detection
			raise Exception("RPi.GPIO must be greater than 0.6")
		GPIO.setmode(GPIO.BCM)  # Use the board numbering scheme
		GPIO.setwarnings(False)  # Disable GPIO warnings

	def on_after_startup(self):
		'''
        Runs after server startup.
        initialises filaemnt sensor object, depending on the settings from the config.yaml file
        logs the number of filament sensors active
        :return: None
        '''
		self.sensorCount = int(self._settings.get(["sensorCount"]))  # senco
		if self.sensorCount != -1:  # If a pin is defined
			bounce = int(self._settings.get(["bounce"]))
			extrudePin = int(self._settings.get(["extrudePin"]))
			minExtrudeTime = int(self._settings.get(["minExtrudeTime"]))
			extruderRunoutTime = float(self._settings.get(["extruderRunoutTime"]))
			filamentRunoutTime = int(self._settings.get(["filamentRunoutTime"]))
			sensor0EncoderPin = int(self._settings.get(["sensor0EncoderPin"]))
			sensor1EncoderPin = int(self._settings.get(["sensor1EncoderPin"]))
			self.sensor0 = filamentSensor(sensorNumber=0, encoderPin=sensor0EncoderPin,
										  filamentRunoutTime=filamentRunoutTime, bounce=bounce)
			self.sensor1 = filamentSensor(sensorNumber=1, encoderPin=sensor1EncoderPin,
										  filamentRunoutTime=filamentRunoutTime, bounce=bounce)
			self.motorExtrusion = motorExtrusion(extrudePin=extrudePin, minExtrudeTime=minExtrudeTime,
												 extruderRunoutTime=extruderRunoutTime, bounce=bounce)
			self._logger.info("FILAMENT SENSOR ENABLED")
		else:
			self._logger.info("FILAMENT SENSOR DISABLED")

		self._worker = RepeatedTimer(2, self.worker)

	def get_settings_defaults(self):
		'''
        initialises default parameters
        :return:
        '''
		return dict(
			sensorCount=2,  # Default is no pin
			sensor0EncoderPin=5,
			sensor1EncoderPin=6,
			extrudePin=13,
			minExtrudeTime=15,
			extruderRunoutTime=0.3,
			filamentRunoutTime=20,
			bounce=100  # Debounce 250ms
		)

	def get_template_configs(self):
		return [dict(type="settings", custom_bindings=False)]

	@octoprint.plugin.BlueprintPlugin.route("/status", methods=["GET"])
	def check_status(self):
		'''
        Checks and sends the pin configuration of the filament sensor(s)
        :return: response  dict of the pin configuration
        '''
		if self._printer.is_printing() or self._printer.is_paused():
			if self.sensorCount != -1:
				return jsonify(sensor0=self.sensor0.getStatus(),sensor1=self.sensor1.getStatus(), motorExtrusion=self.motorExtrusion.getStatus())
			else:
				return jsonify(sensor='No Sensors Connected')
		else:
			return jsonify(status='Printer is not priting')

	@octoprint.plugin.BlueprintPlugin.route("/message", methods=["GET"])
	def message_test(self):
		'''
        Checks and sends the pin configuration of the filament sensor(s)
        :return: response  dict of the pin configuration
        '''
		self._send_status(status_type="Filament_Sensor_Triggered", status_value="error",
						  status_description="Error with filament, please check and resume print")
		return jsonify(status='Message Sent')

	@octoprint.plugin.BlueprintPlugin.route("/enable", methods=["POST"])
	def sensorEnable(self, *args, **kwargs):
		'''
        enables sensors based on sensorCount
        '''
		data = request.json
		if 'sensorCount' in data.keys():
			self.sensorCount = data['sensorCount']
		if self.sensorCount != -1:  # If a pin is defined
			bounce = int(self._settings.get(["bounce"]))
			extrudePin = int(self._settings.get(["extrudePin"]))
			minExtrudeTime = int(self._settings.get(["minExtrudeTime"]))
			extruderRunoutTime = float(self._settings.get(["extruderRunoutTime"]))
			filamentRunoutTime = int(self._settings.get(["filamentRunoutTime"]))
			sensor0EncoderPin = int(self._settings.get(["sensor0EncoderPin"]))
			sensor1EncoderPin = int(self._settings.get(["sensor1EncoderPin"]))

			self.sensor0 = filamentSensor(sensorNumber=0, encoderPin=sensor0EncoderPin,
										  filamentRunoutTime=filamentRunoutTime, bounce=bounce)
			self.sensor1 = filamentSensor(sensorNumber=1, encoderPin=sensor1EncoderPin,
										  filamentRunoutTime=filamentRunoutTime, bounce=bounce)
			self.motorExtrusion = motorExtrusion(extrudePin=extrudePin, minExtrudeTime=minExtrudeTime,
												 extruderRunoutTime=extruderRunoutTime, bounce=bounce)
			self.deactivateFilamentSensing()
		if self._printer.is_printing() or self._printer.is_paused():
			if self.sensorCount == -1:
				self.deactivateFilamentSensing()
				return jsonify(STATUS='SENSOR DISSABLED & DEACTIVATED')
			else:
				self.deactivateFilamentSensing()
				self.activateFilamentSensing()
				return jsonify(STATUS='SENSOR ENABLED & ACTIVATED')
		return jsonify(STATUS='SENSOR ENABLED')

	def on_event(self, event, payload):
		'''
        Enables the filament sensor(s) if a print/resume command is triggered
        Dissables the filament sensor when pause ic called.
        :param event: event to respond to
        :param payload:
        :return:
        '''
		if event in (Events.PRINT_STARTED, Events.PRINT_RESUMED):  # If a new print is beginning
			if self.sensorCount != -1:
				self.deactivateFilamentSensing()
				self.activateFilamentSensing()
		elif event in (
				Events.PRINT_DONE, Events.PRINT_FAILED, Events.PRINT_CANCELLED, Events.PRINT_PAUSED, Events.ERROR):
			if self.sensorCount != -1:
				self.deactivateFilamentSensing()
				self._logger.info("Filament sensor deactivated since print was paused")

	def triggered(self):
		'''
        Callback function called when filament sensor is triggered while printing
        :param sensorNumber: the sensor number that triggered the function
        :return:
        '''

		if self._printer.is_printing():
			self._send_status(status_type="Filament_Sensor_Triggered", status_value="error",
							  status_description="Error with filament, please check and resume print")
			self.deactivateFilamentSensing()
			self._printer.pause_print()
			self._logger.info("Filament Sensor Triggered, Pausing Print")

	def _send_status(self, status_type, status_value, status_description=""):
		self._plugin_manager.send_plugin_message(self._identifier,
												 dict(type="status", status_type=status_type, status_value=status_value,
													  status_description=status_description))

	def deactivateFilamentSensing(self):

		try:
			self.motorExtrusion.dissable()
			self.sensor0.dissable()
			self.sensor1.dissable()
			self._worker.stop()
			self._logger.info("Filament sensor deactivated")

		except Exception:
			pass

	def activateFilamentSensing(self):
		try:
			if self.sensorCount != -1:
				self.motorExtrusion.enable()
				self.sensor0.enable()
				self.sensor1.enable()
				self._worker.start()
				self._logger.info("Filament sensor activated")
			else:
				self._logger.info("No filament sensor to activate because it is dissabld")
		except RuntimeError, e:
			self._logger.info("filament sensors could not be activated: " + str(e))

	def worker(self):
		try:
			if (self.motorExtrusion.isExtruding() and not (
					self.sensor0.isRotating() or self.sensor1.isRotating())):
				self.triggered()
				self._logger.info("Filament sensor triggered")
		except Exception, e:
			self._logger.info("Error in filament checkingThread: " + str(e))

	def get_update_information(self):
		return dict(
			Julia3GFilamentSensor=dict(
				displayName="Julia3GFilamentSensor",
				displayVersion=self._plugin_version,

				# version check: github repository
				type="github_release",
				user="FracktalWorks",
				repo="Julia3GFilamentSensor",
				current=self._plugin_version,

				# update method: pip
				pip="https://github.com/FracktalWorks/Julia3GFilamentSensor/archive/{target_version}.zip"
			)
		)

	def on_settings_save(self, data):
		octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
		self.sensorCount = int(self._settings.get(["sensorCount"]))
		if self.sensorCount != -1:  # If a pin is defined
			bounce = int(self._settings.get(["bounce"]))
			extrudePin = int(self._settings.get(["extrudePin"]))
			minExtrudeTime = int(self._settings.get(["minExtrudeTime"]))
			extruderRunoutTime = float(self._settings.get(["extruderRunoutTime"]))
			filamentRunoutTime = int(self._settings.get(["filamentRunoutTime"]))
			sensor0EncoderPin = int(self._settings.get(["sensor0EncoderPin"]))
			sensor1EncoderPin = int(self._settings.get(["sensor1EncoderPin"]))
			self.sensor0 = filamentSensor(sensorNumber=0, encoderPin=sensor0EncoderPin,
										  filamentRunoutTime=filamentRunoutTime, bounce=bounce)
			self.sensor1 = filamentSensor(sensorNumber=1, encoderPin=sensor1EncoderPin,
										  filamentRunoutTime=filamentRunoutTime, bounce=bounce)
			self.motorExtrusion = motorExtrusion(extrudePin=extrudePin, minExtrudeTime=minExtrudeTime,
												 extruderRunoutTime=extruderRunoutTime, bounce=bounce)
			self.deactivateFilamentSensing()
		self._logger.info("Filament Sensor: New Settings Injected")
		if self._printer.is_printing() or self._printer.is_paused():
			if self.sensorCount == -1:
				self.deactivateFilamentSensing()
				self._logger.info("Filament Sensor Deactivated")
			elif self.sensorCount == 2:
				self.deactivateFilamentSensing()
				self.activateFilamentSensing()
				self._logger.info("Filament Sensor Activated")


class motorExtrusion(object):
	def __init__(self, extrudePin, minExtrudeTime, extruderRunoutTime, bounce):
		self.extrudePin = extrudePin
		self.bounce = bounce
		self.minExtrudeTime = minExtrudeTime
		self.extruderRunoutTime = extruderRunoutTime
		try:
			GPIO.setup(self.extrudePin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
		except:
			self._logger.info("Error while initialising Motor Pins")

	def enable(self):
		GPIO.add_event_detect(self.extrudePin, GPIO.BOTH, callback=self.callback, bouncetime=self.bounce)
		self.latestPulse = time.time()
		self.fallingPulse = time.time()

	def callback(self, channel):
		if bool(GPIO.input(self.extrudePin)) == False:  # Falling Edge detected
			self.fallingPulse = time.time()
		elif time.time() - self.fallingPulse > self.extruderRunoutTime:  # if the low time is too less, disregard
			self.latestPulse = time.time()

	def dissable(self):
		GPIO.remove_event_detect(self.extrudePin)

	def isExtruding(self):
		'''
        If the motor has been extruding for some time, as well as is currently HIGH, means the extruder is extruding
        :return:
        '''
		if (time.time() - self.latestPulse > self.minExtrudeTime) and bool(GPIO.input(self.extrudePin)):
			return True
		else:
			return False

	def getStatus(self):
		return {'isExtruding': self.isExtruding(),
				'extrudePinStatus': bool(GPIO.input(self.extrudePin)),
				'lastExtrude': time.time() - self.latestPulse}


class filamentSensor(object):
	def __init__(self, encoderPin, sensorNumber, filamentRunoutTime, bounce):
		self.sensorNumber = sensorNumber
		self.encoderPin = encoderPin
		self.bounce = bounce
		self.filamentRunoutTime = filamentRunoutTime
		try:
			GPIO.setup(self.encoderPin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
		except:
			self._logger.info("Error while initialising Filament Pins")

	def enable(self):
		GPIO.add_event_detect(self.encoderPin, GPIO.FALLING, callback=self.callback, bouncetime=self.bounce)
		self.latestPulse = time.time()

	def dissable(self):
		GPIO.remove_event_detect(self.encoderPin)

	def callback(self, channel):
		self.latestPulse = time.time()

	def isRotating(self):
		'If the encoder hasnt moved for some time, means the fiament sensor isnt rotating'
		if (time.time() - self.latestPulse > self.filamentRunoutTime):
			return False
		else:
			return True

	def getStatus(self):
		return {'lastEncoderStep': time.time() - self.latestPulse,
				'isRotating': self.isRotating()}


__plugin_name__ = "Julia3GFilamentSensor"
__plugin_version__ = "1.0.4"


def __plugin_load__():
	global __plugin_implementation__
	__plugin_implementation__ = Julia3GFilamentSensor()

	global __plugin_hooks__
	__plugin_hooks__ = {
		"octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
	}
