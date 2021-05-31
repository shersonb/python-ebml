import ast
import types

from ebml.exceptions import UnexpectedEndOfData

def detectVintSize(n):
    for k in range(1, 9):
        if n < 128**k - 1:
            return k

    raise OverflowError

def fromVint(vint):
    b = vint[0]
    k = len(vint)

    if 2**(8 - k) <= b < 2**(9 - k):
        return int.from_bytes(vint, byteorder="big") & ~(1 << (7*k))

    raise ValueError("Invalid data for vint.")

def toVint(n, size=0):
    if size == 0:
        size = detectVintSize(n)

    if n >= 128**size - 1:
        raise OverflowError

    return ((1 << (7*size)) | n).to_bytes(size, "big")

def toVints(a):
    return b"".join(map(toVint, a))

def readVint(file):
    b = file.read(1)

    if len(b) == 0:
        return b""

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

def parseVint(data):
    x = data[0]

    for k in range(1, 9):
        if x & (1 << (8 - k)):
            if len(data) < k:
                raise UnexpectedEndOfData("Unexpected End of Data while scanning variable-length integer")

            return data[:k], data[k:]

    raise ValueError("Invalid Vint.")

def parseVints(data):
    N = len(data)
    offset = 0

    while offset < N:
        x = data[offset]

        for k in range(1, 9):
            if x & (1 << (8 - k)):
                if len(data) < offset + k:
                    raise UnexpectedEndOfData("Unexpected End of Data while scanning variable-length integer")

                yield data[offset : offset + k]
                offset += k
                break

def parseElements(data):
    offset = 0
    n = len(data)

    while offset < n:
        x = data[offset]

        for j in range(1, 9):
            if x & (1 << (8 - j)):
                if n < offset + j:
                    raise UnexpectedEndOfData("Unexpected End of Data while scanning variable-length integer")

                ebmlID = data[offset: offset + j]
                #offset += k
                break

        else:
            raise ValueError("Invalid Vint.")

        x = data[offset + j]

        for k in range(1, 9):
            if x & (1 << (8 - k)):
                if n < offset + j + k:
                    raise UnexpectedEndOfData("Unexpected End of Data while scanning variable-length integer")

                vsize = data[offset + j: offset + j + k]
                size = fromVint(vsize)
                #offset += k
                break

        else:
            raise ValueError("Invalid Vint.")


        if n < offset + j + k + size:
            raise UnexpectedEndOfData("Unexpected End of Data while scanning variable-length integer")

        yield (offset, ebmlID, k, data[offset + j + k: offset + j + k+ size])

        offset += j + k + size

def parseFile(file, size=None):
    nextoffset = start = file.tell()

    while True:
        if size is not None and nextoffset >= start + size:
            break

        file.seek(nextoffset)
        ebmlID = readVint(file)

        if ebmlID == b"":
            raise StopIteration

        esize = readVint(file)
        isize = fromVint(esize)

        if size is not None and nextoffset > start + size:
            raise UnexpectedEndOfData("EBML Element extends past end of data.")

        yield (nextoffset, ebmlID, esize,
               nextoffset + len(ebmlID) + len(esize), isize)

        nextoffset += len(ebmlID) + len(esize) + isize
