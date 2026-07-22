from pipython import GCSDevice

# USB connection does not work on Linux - the ConnectUSB cannot access the controller and returns an error
with GCSDevice('C-863') as pidevice:
    pidevice.ConnectUSB(serialnum='0019550121')
    print(pidevice.qIDN().strip())

# in fact, the USB connection is interpreted on linux as a COM port -

with GCSDevice() as c863:
    c863.OpenRS232DaisyChain(comport=w, baudrate=9600)
    dcid = c863.dcid
    print('dcid =', dcid)

    c863.ConnectDaisyChainDevice(3, dcid)   # example: master address
    print(c863.qIDN().strip())