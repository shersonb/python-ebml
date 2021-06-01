import ast
import types

from ebml.exceptions import UnexpectedEndOfData
from .vint import (detectVintSize, getVintSize, fromVint, toVint, parseVint,
                   parseVints, readVint, peekVint, parseFile, parseElements)

def toVints(a):
    return b"".join(map(toVint, a))

def formatBytes(data):
    return " ".join(f"{x:02X}" for x in data)
