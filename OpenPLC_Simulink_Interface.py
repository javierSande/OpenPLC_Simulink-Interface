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

simulink_ip = ''

PLC_STATIONS_PORT = 6668

class PlcData:
	def __init__(self):
		self.analogIn = [0] * ANALOG_BUF_SIZE
		self.analogOut = [0] * ANALOG_BUF_SIZE
		self.digitalIn = [False] * DIGITAL_BUF_SIZE
		self.digitalOut = [False] * DIGITAL_BUF_SIZE

	def pack(self):
		# Convert boolean lists to integers
		digital_in_int = [int(bit) for bit in self.digitalIn]
		digital_out_int = [int(bit) for bit in self.digitalOut]

        # Pack data using struct
		packed_data = struct.pack(f'{ANALOG_BUF_SIZE}i{ANALOG_BUF_SIZE}i{DIGITAL_BUF_SIZE}?{DIGITAL_BUF_SIZE}?', 
							*self.analogIn, *self.analogOut, *digital_in_int, *digital_out_int)
		return packed_data
		
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
					simulink_ip = getData(line, '"', '"')

				elif line.startswith("station"):
						stationNumber = getStationNumber(line)
						functionType = getFunction(line)
						if functionType == "ip":
							stationsInfo[stationNumber].ip = getData(line, '"', '"')
						elif functionType == "add":
							addPlcPort(line, stationsInfo[stationNumber])

		print("Configuration file loaded!")

def displayInfo():
	print("STATIONS INFO:")

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
		analogOut = stationsData[stationNumber].analogOut[varIndex]
	if varType == Type.DIGITALOUT:
		port = stationsInfo[stationNumber].digitalOutPorts[varIndex]
		digitalOut = stationsData[stationNumber].digitalOut[varIndex]

	# Initialize Server Structures
	try:
		simulinkSocket.connect((socket.gethostbyname(simulink_ip), PLC_STATIONS_PORT))
	except socket.herror:
		print("Error locating host {}".format(simulink_ip))
		return
	except:
		print("Error binding simulink socket")
		return

	while True:
		bufferLock.acquire()
		value = digitalOut if varType == Type.DIGITALOUT else analogOut
		value = 1
		value = value.to_bytes(2)
		print("Sending to port {}".format(port))
		bufferLock.locked()

		"""
		# DEBUG
		print("Sending data type {}, station {}, index {}, value: {}".format(varType.toString(), stationNumber, varIndex, value))
		"""

		dataSentLen = simulinkSocket.send(value)
		if dataSentLen < 0:
			print("Error sending data to simulink on socket {}\n".format(simulinkSocket.fileno()))

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

	print("Socket %d binded successfully on port {}!".format(serverSocket.fileno(), port))

	return serverSocket


# Thread to receive data from Simulink using UDP

def receiveSimulinkData(stationNumber, varType, varIndex):

	rcvData = []

	if varType == Type.ANALOGIN:
		port = stationsInfo[stationNumber].analogInPorts[varIndex]
	if varType == Type.DIGITALIN:
		port = stationsInfo[stationNumber].digitalInPorts[varIndex]

	simulinkSocket = createUDPServer(port)

	while True:
		rcvData = simulinkSocket.recv(BUFF_SIZE)
		rcvDataLen = len(rcvData)
		if rcvDataLen < 0:
			print("Error receiving data on socket {}\n".format(simulinkSocket.fileno()))
		else:
			
			rcvData = struct.unpack('d', rcvData)[0]

			""""
			#DEBUG
			print("Received packet from {}:{}\n".format(simulink_ip, port))
			print("Station: {}, Type: {}, Index: {}, Size: {}, Data: {}\n".format(stationNumber, varType, varIndex, rcvDataLen, rcvData))
			"""
			
			bufferLock.acquire()
			if varType == Type.DIGITALIN: stationsData[stationNumber].digitalIn[varIndex] = bool(rcvData)
			else: stationsData[stationNumber].analogIn[varIndex] = int(rcvData)
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
		print ("Server: error creating stream socket")	

	try:
		ip = socket.gethostbyname(stationsInfo[stationNumber].ip)
		serverSocket.connect((ip, port))
	except socket.herror:
		print("Error locating host {}".format(stationsInfo[stationNumber].ip))
	except:
		print("Error connection to station {} (ip: {})".format(stationNumber, ip))

	# set timeout of 100ms on receive
	serverSocket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVTIMEO, (8*b'\x00')+(100000).to_bytes(8, 'little'))

	while True:
		bufferLock.acquire()
		localBuffer = copy.deepcopy(stationsData[stationNumber])
		bufferLock.release()

		# print("Sending pressure: {} to station: {}".format(localBuffer->pressure, stationNumber))
		serverSocket.send("holamundo".encode())
		print(localBuffer.pack())
		dataSentLen = serverSocket.send(localBuffer.pack())
		if dataSentLen != len(localBuffer.pack()):
			print("Error sending data on socket {}\n".format(serverSocket.fileno()))
		else:
			# print("Receiving data from station {}".format(stationNumber))
			dataRcvLen = 0
			counter = 0
			while dataRcvLen == 0:
				data = serverSocket.recv(BUFF_SIZE).decode()
				try:
					dataRcvLen = len(data)
				except:
					print("Error receiving data")
				counter += 1
				if counter > 10:
					dataLen = -1
					break
				
			if dataRcvLen < 0:
					print("Error receiving data on socket {}".format(serverSocket.fileno))
			else:
				"""
				#DEBUG
				print("Received data with size {}:\r".format(dataLen))
				for i in range(0, ANALOG_BUF_SIZE):
					printf("AIN[{}]: {}\t".format(i, localBuffer.analogIn[i]))
				print("\r")
				for i in range(0, ANALOG_BUF_SIZE):
					printf("AOUT[{}]: {}\t".format(i, localBuffer.analogOut[i]))
				print("\r")
				for i in range(0, DIGITAL_BUF_SIZE):
					print("DIN[{}]: {}\t".format(i, localBuffer.digitalIn[i]))
				print("\r")
				for i in range(0, DIGITAL_BUF_SIZE):
					print("DOUT[{}]: {}\t".format(i, localBuffer.digitalOut[i]))
				print("\r")
				"""
				bufferLock.acquire()
				stationsData[stationNumber] = localBuffer
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

while True:

	bufferLock.acquire()

	for i in range(0, numStations):
		print("Station " + str(i) + ":")
		print("Button: {}\tLamp: {}\n".format(int(stationsData[i].digitalIn[0]), int(stationsData[i].digitalOut[0])))

	bufferLock.release()
	sleep(3)