# USB connection does not work on Linux - the ConnectUSB cannot access the controller and returns an error. Therefore,
# we need to use the RS232 communication to access the controller. Also, USB port cannot be addressed by id. The path
# is too long and return a "buffer overflow" error.
# The following script is used to the connection for the PI stages on the spinning disk setup.

from time import sleep
from pipython import GCSDevice, pitools
from pathlib import Path


def resolve_serial_port(by_id_path: str) -> str:
    port_path = Path(by_id_path)

    if not port_path.exists():
        raise FileNotFoundError(f'Serial device not found: {by_id_path}')

    resolved_path = port_path.resolve()

    if not resolved_path.name.startswith(('ttyUSB', 'ttyACM')):
        raise RuntimeError(
            f'Unexpected serial-device target: {resolved_path}'
        )

    return str(resolved_path)

def initialize(serial_address, controller_type, initialization_method):

    with GCSDevice(controller_type) as pidevice:
        pidevice.ConnectRS232(comport=serial_address, baudrate=9600)
        print(f'{pidevice.GetInterfaceDescription()}: {pidevice.qIDN().strip()}')
        pitools.startup(pidevice, refmodes=None)
        print(pidevice.axes)

        ron_command = getattr(pidevice, 'RON', None)
        if callable(ron_command):
            ron_command(pidevice.axes[0], values=1)
        else:
            print("command 'RON' not callable")

        reference_command = getattr(pidevice, initialization_method, None)
        if callable(reference_command):
            reference_command(pidevice.axes[0])
        else:
            print(f"command {initialization_method} not callable")

    sleep(5)
    pidevice.CloseConnection()


# Z-axis

try :
    serial_id = '/dev/serial/by-id/usb-PI_PI_C-863_Mercury_16HU24A_-if00-port0'
    serial_port = resolve_serial_port(serial_id)
    initialize(serial_port, 'C-863', 'FNL')
except Exception as error:
    print("Z stage was not properly initialized - the following error was detected :")
    print(error)

# r-axis
try:
    serial_id = '/dev/serial/by-id/usb-PI_PI_C-863_Mercury-if00-port0'
    serial_port = resolve_serial_port(serial_id)
    initialize(serial_port, 'C-863', 'FNL')
except Exception as error:
    print("R (radial) stage was not properly initialized - the following error was detected :")
    print(error)


# phi-axis
try:
    serial_id = '/dev/serial/by-id/usb-PI_PI_C-867_Piezomotor_Controller_14ASKLJ_-if00-port0'
    serial_port = resolve_serial_port(serial_id)
    initialize(serial_port, 'C-867', 'FRF')
except Exception as error:
    print("R (radial) stage was not properly initialized - the following error was detected :")
    print(error)