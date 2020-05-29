import ast
import types

from ebml.exceptions import UnexpectedEndOfData

def fromVint(vint):
    b = vint[0]
    k = len(vint)

    if 2**(8 - k) <= b < 2**(9 - k):
        return int.from_bytes(vint, byteorder="big") & ~(1 << (7*k))

    raise ValueError("Invalid data for vint.")

def toVint(n, size=0):
    if size == 0:
        for k in range(1, 9):
            if n < 128**k - 1:
                return ((1 << (7*k)) | n).to_bytes(k, "big")

        else:
            raise OverflowError

    else:
        if n >= 128**size - 1:
            raise OverflowError

        return ((1 << (7*size)) | n).to_bytes(size, "big")

def readVint(file):
    if isinstance(file, bytes):
        x = file[0]

        for k in range(1, 9):
            if x & (1 << (8 - k)):
                if len(file) < k:
                    raise UnexpectedEndOfData("Unexpected End of Data while scanning variable-length integer")

                return file[:k]

        raise ValueError("Invalid Vint.")

    b = file.read(1)

    if len(b) == 0:
        raise UnexpectedEndOfData("Unexpected End of Data while scanning variable-length integer")

    x = int.from_bytes(b, byteorder="big")

    for k in range(1, 9):
        if x & (1 << (8 - k)):
            data = file.read(k - 1)

            if len(data) < k - 1:
                raise UnexpectedEndOfData("Unexpected End of Data while scanning variable-length integer")

            return b + data

def formatBytes(data):
    return " ".join([f"{x:02X}" for x in data])

def peekVint(file, peekoffset=0):
    tell = file.tell()
    data = file.read(peekoffset + 8)
    file.seek(tell)
    x = data[peekoffset]

    for k in range(1, 9):
        if x & (1 << (8 - k)):
            if len(data) < peekoffset + k:
                raise UnexpectedEndOfData("Unexpected End of Data while scanning variable-length integer")

            return data[peekoffset:peekoffset+k]

