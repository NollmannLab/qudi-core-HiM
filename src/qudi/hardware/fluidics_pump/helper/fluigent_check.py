import Fluigent.SDK as fgt

print("detect:", fgt.fgt_detect())
print("init:", fgt.fgt_init())
print("controllers:", fgt.fgt_get_controllersInfo(get_error=True))
print("pressure count:", fgt.fgt_get_pressureChannelCount(get_error=True))
print("pressure info:", fgt.fgt_get_pressureChannelsInfo(get_error=True))
print("sensor count:", fgt.fgt_get_sensorChannelCount(get_error=True))
print("sensor info:", fgt.fgt_get_sensorChannelsInfo(get_error=True))
fgt.fgt_close()