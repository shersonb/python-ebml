import ast
import types

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
