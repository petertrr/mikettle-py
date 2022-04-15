""""
Read data from Mi Kettle.
"""

import logging
from bluepy.btle import UUID, Peripheral, DefaultDelegate, ADDR_TYPE_RANDOM, BTLEInternalError
from datetime import datetime, timedelta
from threading import Lock
import time

_KEY1 = bytes([0x90, 0xCA, 0x85, 0xDE])
_KEY2 = bytes([0x92, 0xAB, 0x54, 0xFA])

_HANDLE_READ_FIRMWARE_VERSION = 26
_HANDLE_READ_MANU = 18
_HANDLE_READ_NAME = 20
_HANDLE_AUTH_INIT = 44
_HANDLE_AUTH = 37
_HANDLE_VERIFY = 42
_HANDLE_STATUS = 61
_HANDLE_KW = 58
_HANDLE_KW_TIME = 65
_HANDLE_EWU = 68

_UUID_SERVICE_KETTLE = "fe95"
_UUID_SERVICE_KETTLE_DATA = "01344736-0000-1000-8000-262837236156"

_SUBSCRIBE_TRUE = bytes([0x01, 0x00])

MI_ACTION = "action"
MI_MODE = "mode"
MI_SET_TEMPERATURE = "set temperature"
MI_CURRENT_TEMPERATURE = "current temperature"
MI_KW_TYPE = "keep warm type"
MI_CURRENT_KW_TIME = "current keep warm time"
MI_SET_KW_TIME = "set keep warm time"
MI_EWU = "extended warm up"

MI_ACTION_MAP = {
    0: "idle",
    1: "heating",
    2: "cooling",
    3: "keeping warm"
}

MI_MODE_MAP = {
    255: "none",
    1: "boil",
    2: "keep warm"
}

MI_KW_TYPE_MAP = {
    0: "boil and cool down to set temperature",
    1: "warm up to set temperature"
}

MI_EWU_MAP = {
    0: "true",
    1: "false"
}

_LOGGER = logging.getLogger(__name__)


class MiKettle(object):
    """"
    A class to control mi kettle device.
    """

    def __init__(self, mac, product_id, cache_timeout=600, retries=3, iface=None, token=None):
        """
        Initialize a Mi Kettle for the given MAC address.
        """
        _LOGGER.debug('Init Mikettle with mac %s and pid %s', mac, product_id)

        self._mac = mac
        self._reversed_mac = MiKettle.reverseMac(mac)

        self._cache = None
        self._cache_timeout = timedelta(seconds=cache_timeout)
        self._last_read = None
        self.retries = retries
        self.ble_timeout = 10
        self.lock = Lock()

        self._product_id = product_id
        self._iface = iface
        # Generate token if not supplied
        if token is None:
            token = MiKettle.generateRandomToken()
        self._token = token

        self._p = None
        self._authenticated = False

    def connect(self):
        if self._p is None:
            _LOGGER.debug("Attempt to connect, because cached connection is not yet available")
            self._p = Peripheral(deviceAddr=self._mac, iface=self._iface)  # addrType=ADDR_TYPE_RANDOM)
            self._p.setDelegate(self)

    def name(self):
        """Return the name of the device."""
        self.connect()
        self.auth()
        name = self._p.readCharacteristic(_HANDLE_READ_NAME)

        if not name:
            raise Exception("Could not read NAME using handle %s"
                            " from Mi Kettle %s" % (_HANDLE_READ_NAME, self._mac))
        return ''.join(chr(n) for n in name)

    def manufacturer(self):
        """Return the manufacturer of the device."""
        self.connect()
        self.auth()
        name = self._p.readCharacteristic(_HANDLE_READ_MANU)

        if not name:
            raise Exception("Could not read MANUFACTURER using handle %s"
                            " from Mi Kettle %s" % (_HANDLE_READ_NAME, self._mac))
        return ''.join(chr(n) for n in name)

    def firmware_version(self):
        """Return the firmware version."""
        self.connect()
        self.auth()
        firmware_version = self._p.readCharacteristic(_HANDLE_READ_FIRMWARE_VERSION)

        if not firmware_version:
            raise Exception("Could not read FIRMWARE_VERSION using handle %s"
                            " from Mi Kettle %s" % (_HANDLE_READ_FIRMWARE_VERSION, self._mac))
        return ''.join(chr(n) for n in firmware_version)

    def KW(self):
        """Return the Keep Warm Type and Keep Warm Temp."""
        self.connect()
        self.auth()
        data = self._p.readCharacteristic(_HANDLE_KW)

        kwType = MI_KW_TYPE_MAP[int(data[0])]
        kwTemp = int(data[1])

        return kwType, kwTemp

    def setKW(self, KWtype: int, temperature: int):
        """Set the Keep Warm Type and Keep Warm Temperature.
        Type is 0 or 1, temperature is """
        self.connect()
        self.auth()
        self._p.writeCharacteristic(_HANDLE_KW, bytes([KWtype,temperature]), "true")
#        self.clear_cache()

    def KWTime(self):
        """Return the Keep Warm Time."""
        self.connect()
        self.auth()
        data = self._p.readCharacteristic(_HANDLE_KW_TIME)

        kwTime = int(data[0])

        return kwTime

    def setKWTime(self,time):
        """Set the Keep Warm Time."""
        self.connect()
        self.auth()
        self._p.writeCharacteristic(_HANDLE_KW_TIME, bytes([time]), "true")

    def EWU(self):
        """Return whether extended warm up is set."""
        self.connect()
        self.auth()
        data = self._p.readCharacteristic(_HANDLE_EWU)

        ewu = MI_EWU_MAP[int(data[0])]

        return ewu

    def setEWU(self,mode):
        """Set extended warm up."""
        self.connect()
        self.auth()
        self._p.writeCharacteristic(_HANDLE_EWU, bytes([mode]), "true")

    def parameter_value(self, parameter, read_cached=True):
        """Return a value of one of the monitored paramaters.
        This method will try to retrieve the data from cache and only
        request it by bluetooth if no cached value is stored or the cache is
        expired.
        This behaviour can be overwritten by the "read_cached" parameter.
        """
        # Use the lock to make sure the cache isn't updated multiple times
        with self.lock:
            if (read_cached is False) or \
                    (self._last_read is None) or \
                    (datetime.now() - self._cache_timeout > self._last_read):
                self.fill_cache()
            else:
                _LOGGER.debug("Using cache (%s < %s)",
                              datetime.now() - self._last_read,
                              self._cache_timeout)

        if self.cache_available():
            return self._cache[parameter]
        else:
            raise Exception("Could not read data from MiKettle %s" % self._mac)

    def fill_cache(self):
        """Fill the cache with new data from the sensor."""
        _LOGGER.debug('Filling cache with new sensor data.')
        for i in range(self.retries):
            _LOGGER.debug("Connection attempt {} of {}".format(i + 1, self.retries))
            try:
                _LOGGER.debug('Connect')
                self.connect()
                _LOGGER.debug('Auth')
                self.auth()
                _LOGGER.debug('Subscribe')
                self.subscribeToData()
                _LOGGER.debug('Wait for data')
                self._p.waitForNotifications(self.ble_timeout)
                break
            except BTLEInternalError as ble_error:
                _LOGGER.debug("BTLEInternalError {}".format(ble_error))
                if self._p is not None:
                    self._p.disconnect()
                    self._p = None
                    self._authenticated = False
                # If a sensor doesn't work, wait 5 minutes before retrying
            except Exception as error:
                _LOGGER.debug('Error %s', error)
                if i == self.retries - 1:
                    self._last_read = datetime.now() - self._cache_timeout + \
                        timedelta(seconds=300)
                    return
                time.sleep(3)

    def clear_cache(self):
        """Manually force the cache to be cleared."""
        self._cache = None
        self._last_read = None

    def cache_available(self):
        """Check if there is data in the cache."""
        return self._cache is not None

    def _parse_data(self, data):
        """Parses the byte array returned by the sensor."""
        res = dict()
        res[MI_ACTION] = MI_ACTION_MAP[int(data[0])]
        res[MI_MODE] = MI_MODE_MAP[int(data[1])]
        res[MI_SET_TEMPERATURE] = int(data[4])
        res[MI_CURRENT_TEMPERATURE] = int(data[5])
        res[MI_KW_TYPE] = MI_KW_TYPE_MAP[int(data[6])]
        res[MI_CURRENT_KW_TIME] = MiKettle.bytes_to_int(data[7:8])
        res[MI_EWU] = MI_EWU_MAP[int(data[9])]
        res[MI_SET_KW_TIME] = int(data[10])
        return res

    @staticmethod
    def bytes_to_int(bytes):
        result = 0
        for b in bytes:
            result = result * 256 + int(b)

        return result

    def auth(self):
        if self._authenticated:
            return
        _LOGGER.debug("Attempt to auth, because self._authenticated is False")
        auth_service = self._p.getServiceByUUID(_UUID_SERVICE_KETTLE)
        auth_descriptors = auth_service.getDescriptors()

        self._p.writeCharacteristic(_HANDLE_AUTH_INIT, _KEY1, "true")

        auth_descriptors[1].write(_SUBSCRIBE_TRUE, "true")

        self._p.writeCharacteristic(_HANDLE_AUTH,
                                    MiKettle.cipher(MiKettle.mixA(self._reversed_mac, self._product_id), self._token),
                                    "true")

        self._p.waitForNotifications(10.0)

        self._p.writeCharacteristic(_HANDLE_AUTH, MiKettle.cipher(self._token, _KEY2), "true")

        self._p.readCharacteristic(_HANDLE_VERIFY)
        self._authenticated = True

    def subscribeToData(self):
        controlService = self._p.getServiceByUUID(_UUID_SERVICE_KETTLE_DATA)
        controlDescriptors = controlService.getDescriptors()
        controlDescriptors[3].write(_SUBSCRIBE_TRUE, "true")

    # TODO: Actually generate random token instead of static one
    @staticmethod
    def generateRandomToken() -> bytes:
        return bytes([0x01, 0x5C, 0xCB, 0xA8, 0x80, 0x0A, 0xBD, 0xC1, 0x2E, 0xB8, 0xED, 0x82])

    @staticmethod
    def reverseMac(mac) -> bytes:
        parts = mac.split(":")
        reversedMac = bytearray()
        leng = len(parts)
        for i in range(1, leng + 1):
            reversedMac.extend(bytearray.fromhex(parts[leng - i]))
        return reversedMac

    @staticmethod
    def mixA(mac, productID) -> bytes:
        return bytes([mac[0], mac[2], mac[5], (productID & 0xff), (productID & 0xff), mac[4], mac[5], mac[1]])

    @staticmethod
    def mixB(mac, productID) -> bytes:
        return bytes([mac[0], mac[2], mac[5], ((productID >> 8) & 0xff), mac[4], mac[0], mac[5], (productID & 0xff)])

    @staticmethod
    def _cipherInit(key) -> bytes:
        perm = bytearray()
        for i in range(0, 256):
            perm.extend(bytes([i & 0xff]))
        keyLen = len(key)
        j = 0
        for i in range(0, 256):
            j += perm[i] + key[i % keyLen]
            j = j & 0xff
            perm[i], perm[j] = perm[j], perm[i]
        return perm

    @staticmethod
    def _cipherCrypt(input, perm) -> bytes:
        index1 = 0
        index2 = 0
        output = bytearray()
        for i in range(0, len(input)):
            index1 = index1 + 1
            index1 = index1 & 0xff
            index2 += perm[index1]
            index2 = index2 & 0xff
            perm[index1], perm[index2] = perm[index2], perm[index1]
            idx = perm[index1] + perm[index2]
            idx = idx & 0xff
            outputByte = input[i] ^ perm[idx]
            output.extend(bytes([outputByte & 0xff]))

        return output

    @staticmethod
    def cipher(key, input) -> bytes:
        perm = MiKettle._cipherInit(key)
        return MiKettle._cipherCrypt(input, perm)

    def handleNotification(self, cHandle, data):
        if cHandle == _HANDLE_AUTH:
            if(MiKettle.cipher(MiKettle.mixB(self._reversed_mac, self._product_id),
                               MiKettle.cipher(MiKettle.mixA(self._reversed_mac,
                                                             self._product_id),
                                               data)) != self._token):
                raise Exception("Authentication failed.")
        elif cHandle == _HANDLE_STATUS:
            _LOGGER.debug("Status update:")
            if data is None:
              return

            _LOGGER.debug(f"Parse data: {data} / {data.hex()}")
            self._cache = self._parse_data(data)
            _LOGGER.debug(f"data parsed {self._cache}")

            if self.cache_available():
                self._last_read = datetime.now()
            else:
                # If a sensor doesn't work, wait 5 minutes before retrying
                self._last_read = datetime.now() - self._cache_timeout + \
                    timedelta(seconds=300)
        else:
            _LOGGER.error("Unknown notification from handle: %s with Data: %s", cHandle, data.hex())
