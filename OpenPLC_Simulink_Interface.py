from enum import Enum
from time import sleep
import socket
import threading
import re
import copy
import struct

# Types
class Type(Enum):
	ANALOGIN = 0
	ANALOGOUT = 1
	DIGITALIN = 2
	DIGITALOUT = 3

	def toString(self):
		if self.value ==  Type.ANALOGIN:
			return "TYPE_ANALOGIN"
		if self.value == Type.ANALOGOUT:
			return "TYPE_ANALOGOUT"
		if self.value == Type.DIGITALIN:
			return "TYPE_DIGITALIN"
		if self.value == Type.DIGITALOUT:
			return "TYPE_DIGITALOUT"

BUFF_SIZE = 8192
ANALOG_BUF_SIZE = 8
DIGITAL_BUF_SIZE = 16

COMMDELAY = 0.1

simulinkIp = ''

PLC_STATIONS_PORT = 6668

class PlcData:
	def __init__(self):
		self.analogIn = [0] * ANALOG_BUF_SIZE
		self.analogOut = [0] * ANALOG_BUF_SIZE
		self.digitalIn = [False] * DIGITAL_BUF_SIZE
		self.digitalOut = [False] * DIGITAL_BUF_SIZE

	def pack(self):
		# Pack data using struct
		packedData = struct.pack(f'{ANALOG_BUF_SIZE}H{ANALOG_BUF_SIZE}H{DIGITAL_BUF_SIZE}?{DIGITAL_BUF_SIZE}?', *self.analogIn, *self.analogOut, *self.digitalIn, *self.digitalOut)
		return packedData

	def unpack(self, packedData):
		unpackedData = struct.unpack(f'{ANALOG_BUF_SIZE}H{ANALOG_BUF_SIZE}H{DIGITAL_BUF_SIZE}?{DIGITAL_BUF_SIZE}?', packedData)
		self.analogIn = list(unpackedData[:ANALOG_BUF_SIZE])
		self.analogOut = list(unpackedData[ANALOG_BUF_SIZE: 2 * ANALOG_BUF_SIZE])
		self.digitalIn= list(unpackedData[2*ANALOG_BUF_SIZE:2*ANALOG_BUF_SIZE+DIGITAL_BUF_SIZE])
		self.digitalOut= list(unpackedData[2*ANALOG_BUF_SIZE+DIGITAL_BUF_SIZE:])

	def print(self):
		print("Analog In: {}".format(self.analogIn))
		print("Analog Out: {}".format(self.analogOut))
		print("Digital In: {}".format(self.digitalIn))
		print("Digital Out: {}".format(self.digitalOut))
		print()

class StationInfo:
	def __init__(self):
		self.ip = ""
		self.analogInPorts = []
		self.analogOutPorts = []
		self.digitalInPorts = []
		self.digitalOutPorts = []

numStations = 0
stationsData = []
stationsInfo = []

bufferLock = threading.Lock()

# Finds the data between the separators on the line provided

def getData(line, separator1, separator2):
	sep1Idx = line.find(separator1)
	sep2Idx = line[sep1Idx + 1:].find(separator2) + sep1Idx + 1
	if sep1Idx >= 0 and sep1Idx < sep2Idx:
		return line[sep1Idx + 1:sep2Idx]
	return ''


# Get the number of the station

def getStationNumber(line):
	return int(line[7:].split('.')[0])


# get the type of function or parameter for the station

def getFunction(line):
	line = line.split('.')[1]
	return re.split(r'=|\(', line)[0].strip()


# Add the UDP Port number to the plc station info

def addPlcPort(line, stationInfo):

	type = getData(line, '(', ')')
	data = int(getData(line,'"', '"'))

	if type == "digital_in":
		stationInfo.digitalInPorts.append(data)
	if type == "digital_out":
		stationInfo.digitalOutPorts.append(data)
	if type == "analog_in":
		stationInfo.analogInPorts.append(data)
	if type == "analog_out":
		stationInfo.analogOutPorts.append(data)


# Parse the interface.cfg file looking for the IP address of the Simulink app
# and for each OpenPLC station information

def parseConfigFile():
	global numStations
	global stationsInfo
	global stationsData
	global simulinkIp

	with open("interface.cfg", "r") as cfgfile:
		for line in cfgfile:
			if line[0] != '#' and len(line) > 1:
				if line.startswith("num_stations"):
					numStations = int(getData(line, '"', '"'))
					stationsData = [PlcData() for _ in range(0,numStations)]
					stationsInfo = [StationInfo() for _ in range(0,numStations)]
				elif line.startswith("comm_delay"):
						comm_delay = int(getData(line,'"', '"'))
				elif line.startswith("simulink"):
					simulinkIp = getData(line, '"', '"')

				elif line.startswith("station"):
						stationNumber = getStationNumber(line)
						functionType = getFunction(line)
						if functionType == "ip":
							stationsInfo[stationNumber].ip = getData(line, '"', '"')
						elif functionType == "add":
							addPlcPort(line, stationsInfo[stationNumber])

		print("Configuration file loaded!")

def displayInfo():
	print("\nSTATIONS INFO:")

	for (i,stationInfo) in enumerate(stationsInfo):
		print("\nStation {}:".format(i))
		print("ip: {}".format(stationInfo.ip))

		for (j,port) in enumerate(stationInfo.analogInPorts):
			print("AnalogIn {}: {}".format(j, port))

		for (j,port) in enumerate(stationInfo.analogOutPorts):
			print("AnalogOut {}: {}".format(j, port));

		for (j,port) in enumerate(stationInfo.digitalInPorts):
			print("DigitalIn {}: {}".format(j, port))

		for (j,port) in enumerate(stationInfo.digitalOutPorts):
			print("DigitalOut {}: {}".format(j, port));
	print()

# Thread to send data to Simulink using UDP

def sendSimulinkData(stationNumber, varType, varIndex):

	# Create UDP Socket
	simulinkSocket = socket.socket(socket.AF_INET, # Internet
							       socket.SOCK_DGRAM) # UDP

	# Figure out information about variable
	if varType == Type.ANALOGOUT:
		port = stationsInfo[stationNumber].analogOutPorts[varIndex]
	if varType == Type.DIGITALOUT:
		port = stationsInfo[stationNumber].digitalOutPorts[varIndex]

	# Initialize Server Structures
	try:
		server = socket.gethostbyname(simulinkIp)
		simulinkSocket.connect((server, port))
	except:
		print("Simulink: Error locating host {}".format(simulinkIp))
		return

	while True:
		bufferLock.acquire()
		if varType == Type.ANALOGOUT:
			value = stationsData[stationNumber].analogOut[varIndex]
		if varType == Type.DIGITALOUT:
			value = int(stationsData[stationNumber].digitalOut[varIndex])
		bufferLock.release()
		
		value = struct.pack(f'H', value)

		""""
		# DEBUG
		print("Simulink: Sending data type {}, station {}, index {}, value: {}".format(varType.toString(), stationNumber, varIndex, value))
		print("Port: {}\tData {}".format(port, value))
		"""

		dataSentLen = simulinkSocket.send(value)
		if dataSentLen < 0:
			print("Simulink: Error sending data to simulink on socket {}\n".format(simulinkSocket.fileno()))

		sleep(COMMDELAY)

# Create the socket and bind it. Returns the file descriptor for the socket
# created.

def createUDPServer(port):
	# Create UDP Socket
	serverSocket = socket.socket(socket.AF_INET, # Internet
							     socket.SOCK_DGRAM) # UDP

	# Initialize Server Struct
	serverAddress = ('', port)

	# Bind socket
	serverSocket.bind(serverAddress)

	print("Simulink: Socket {} binded successfully on port {}!".format(serverSocket.fileno(), port))

	return serverSocket

# Thread to receive data from Simulink using UDP

def receiveSimulinkData(stationNumber, varType, varIndex):

	simRcvData = []

	if varType == Type.ANALOGIN:
		port = stationsInfo[stationNumber].analogInPorts[varIndex]
	if varType == Type.DIGITALIN:
		port = stationsInfo[stationNumber].digitalInPorts[varIndex]

	try:
		simulinkSocket = createUDPServer(port)
	except:
		print("Simulink: Error creating UPD server")
		return

	while True:
		simRcvData = simulinkSocket.recv(BUFF_SIZE)
		simRcvDataLen = len(simRcvData)
		if simRcvDataLen < 0:
			print("Simulink: Error receiving data on socket {}\n".format(simulinkSocket.fileno()))
		else:
			
			simRcvData = struct.unpack('d', simRcvData)[0]

			""""
			#DEBUG
			print("Simulink: Received packet from {}:{}".format(simulinkIp, port))
			print("Station: {}, Type: {}, Index: {}, Size: {}, Data: {}\n".format(stationNumber, varType, varIndex, rcvDataLen, rcvData))
			"""
			
			bufferLock.acquire()
			if varType == Type.DIGITALIN: stationsData[stationNumber].digitalIn[varIndex] = bool(simRcvData)
			else: stationsData[stationNumber].analogIn[varIndex] = int(simRcvData)
			bufferLock.release()


# Main function responsible to exchange data with the simulink application

def exchangeDataWithSimulink():
	for (i, stationInfo) in enumerate(stationsInfo): 
		# sending analog data
		for (j, _) in enumerate(stationInfo.analogOutPorts):
			args = [0] * 3
			args[0] = i # station number
			args[1] = Type.ANALOGOUT # var type
			args[2] = j # var index

			t = threading.Thread(target=sendSimulinkData, args=args)
			t.daemon = True
			t.start()

		# receiving analog data
		for (j, _) in enumerate(stationInfo.analogInPorts):
			args = [0] * 3
			args[0] = i # station number
			args[1] = Type.ANALOGIN # var type
			args[2] = j # var index

			t = threading.Thread(target=receiveSimulinkData, args=args)
			t.daemon = True
			t.start()

		# sending digital data
		for (j, _) in enumerate(stationInfo.digitalOutPorts):
			args = [0] * 3
			args[0] = i # station number
			args[1] = Type.DIGITALOUT # var type
			args[2] = j # var index

			t = threading.Thread(target=sendSimulinkData, args=args)
			t.daemon = True
			t.start()

		# receiving digital data
		for (j, _) in enumerate(stationInfo.digitalInPorts):
			args = [0] * 3
			args[0] = i # station number
			args[1] = Type.DIGITALIN # var type
			args[2] = j # var index

			t = threading.Thread(target=receiveSimulinkData, args=args)
			t.daemon = True
			t.start()


def exchangeDataWithPLC(stationNumber):

	port = PLC_STATIONS_PORT

	#Create TCP Socket

	try:
		serverSocket = socket.socket(socket.AF_INET, # Internet 
							         socket.SOCK_DGRAM) # UDP
	except socket.error: 
		print ("PLC: error creating stream socket")	

	try:
		ip = socket.gethostbyname(stationsInfo[stationNumber].ip)
		serverSocket.connect((ip, port))
		print ("PLC: connected with station {}".format(stationNumber))
	except socket.herror:
		print("PLC: Error locating host {}".format(stationsInfo[stationNumber].ip))
	except:
		print("PLC: Error connection to station {} (ip: {})".format(stationNumber, ip))

	# set timeout of 100ms on receive
	serverSocket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVTIMEO, (8*b'\x00')+(100000).to_bytes(8, 'little'))

	while True:
		bufferLock.acquire()
		dataToSend = stationsData[stationNumber].pack()
		bufferLock.release()

		# print("Sending data to station: {}".format(stationNumber))
		# print(dataToSend)
		dataSentLen = serverSocket.send(dataToSend)
		if dataSentLen != len(dataToSend):
			print("PLC: Error sending data on socket {}\n".format(serverSocket.fileno()))
		else:
			# print("Receiving data from station {}".format(stationNumber))
			rcvDataLen = 0
			counter = 0
			rcvData = PlcData()
			while rcvDataLen == 0:
				try:
					data = serverSocket.recv(BUFF_SIZE)
					rcvDataLen = len(data)
					rcvData.unpack(data)
					# print(data)
				except:
					rcvDataLen = 0

				counter += 1
				if counter > 10:
					dataLen = -1
					break
				
			if rcvDataLen < 0:
					print("PLC: Error receiving data on socket {}".format(serverSocket.fileno))
			else:
				"""
				#DEBUG
				print("PLC: Received data with size {}:\r".format(rcvDataLen))
				for i in range(0, ANALOG_BUF_SIZE):
					print("AIN[{}]: {}\t".format(i, rcvData.analogIn[i]))
				print("\r")
				for i in range(0, ANALOG_BUF_SIZE):
					print("AOUT[{}]: {}\t".format(i, rcvData.analogOut[i]))
				print("\r")
				for i in range(0, DIGITAL_BUF_SIZE):
					print("DIN[{}]: {}\t".format(i, int(rcvData.digitalIn[i])))
				print("\r")
				for i in range(0, DIGITAL_BUF_SIZE):
					print("DOUT[{}]: {}\t".format(i, int(rcvData.digitalOut[i])))
				print("\r")
				"""
				bufferLock.acquire()
				stationsData[stationNumber] = rcvData
				bufferLock.release()

		sleep(COMMDELAY)


def connectToPLCStations():
	for i in range(0, numStations):
		args = [i]
		t = threading.Thread(target=exchangeDataWithPLC, args=args)
		t.daemon = True
		t.start()


# Interface main function. Should parse the configuration file, call the
# functions to exchange data with the simulink application and with the
# OpenPLC stations. The main loop must also display periodically the data
# exchanged with each OpenPLC station.

parseConfigFile()

displayInfo()

exchangeDataWithSimulink()

connectToPLCStations()

sleep(2)

while True:

	bufferLock.acquire()

	for i in range(0, numStations):
		print("\nStation " + str(i) + ":")
		print("Button: {}\tLamp: {}".format(int(stationsData[i].digitalIn[0]), int(stationsData[i].digitalOut[0])))

	bufferLock.release()
	sleep(3)
