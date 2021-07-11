import ast
import types
import signal
import ctypes
import ctypes.util
import threading

c_off_t = ctypes.c_int64


from ebml.exceptions import UnexpectedEndOfData

# Imports for compatibility purposes, in case some modules still expect these
# functions to still be here.
from .vint import (detectVintSize, getVintSize, fromVint, toVint, parseVint,
                   parseVints, readVint, peekVint, parseFile, parseElements)


def toVints(a):
    return b"".join(map(toVint, a))


def formatBytes(data):
    return " ".join(f"{x:02X}" for x in data)


class Constant(object):
    def __init__(self, value):
        self.value = value

    def __get__(self, inst=None, cls=None):
        if inst is None:
            return self

        return self.value

def make_fallocate():
    libc_name = ctypes.util.find_library('c')
    libc = ctypes.CDLL(libc_name)

    _fallocate = libc.fallocate
    _fallocate.restype = ctypes.c_int
    _fallocate.argtypes = [ctypes.c_int, ctypes.c_int, c_off_t, c_off_t]

    del libc
    del libc_name

    def fallocate(fd, mode, offset, len_):
        res = _fallocate(fd.fileno(), mode, offset, len_)
        if res != 0:
            raise IOError(res, 'fallocate')

    return fallocate

_fallocate = make_fallocate()
del make_fallocate

FALLOC_FL_KEEP_SIZE = 0x01
FALLOC_FL_PUNCH_HOLE = 0x02
FALLOC_FL_COLLAPSE_RANGE = 0x08
FALLOC_FL_INSERT_RANGE = 0x20


class NoInterrupt(object):
    """
    Context manager used to perform a sequence of IO operations that
    must not be interrupted with KeyboardInterrupt.
    """

    def __enter__(self):
        self._signal_received = False

        if threading.currentThread() is threading.main_thread():
            self._old_handler = signal.signal(signal.SIGINT, self.handler)

    def handler(self, sig, frame):
        self._signal_received = (sig, frame)

    def __exit__(self, type, value, traceback):
        if threading.currentThread() is threading.main_thread():
            signal.signal(signal.SIGINT, self._old_handler)

            if self._signal_received:
                self._old_handler(*self._signal_received)


