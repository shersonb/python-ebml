from libc.stdio cimport *
from ebml.exceptions import UnexpectedEndOfData
from libc.stdlib cimport malloc, free


cdef unsigned char _getVintSize(unsigned char b) nogil except *:
    cdef unsigned char k = 0
    cdef unsigned char o = 128

    for k in range(0, 8):
        if b & (o >> k):
            return k + 1

    with gil:
        raise ValueError("Invalid data for vint.")

cpdef unsigned char getVintSize(bytes data, unsigned long long offset=0):
    """Gets the size of a vint from its first byte."""
    cdef unsigned char b = data[offset]

    with nogil:
        return _getVintSize(b)

cdef unsigned char _detectVintSize(long n) nogil except *:
    cdef unsigned long k = 0
    cdef unsigned long long o = 1

    for k in range(1, 9):
        if n < (o << (7*k)) - 1:
            return k

    raise OverflowError

cpdef int detectVintSize(long n) except *:
    """Detects the minimum vint width needed for an integer 'n'."""
    with nogil:
        return _detectVintSize(n)

cpdef long fromVint(bytes vint) except *:
    cdef unsigned int b = vint[0]
    cdef unsigned char k = len(vint)
    cdef unsigned char expected
    cdef unsigned long long o = 1

    with nogil:
        expected = _getVintSize(b)

        if k == expected:
            with gil:
                return long.from_bytes(vint, byteorder="big") & ~(o << (7*k))

    raise ValueError("Invalid data for vint.")

cpdef bytes toVint(unsigned long long n, unsigned int size=0):
    cdef unsigned long long k
    cdef unsigned long long o = 1

    with nogil:
        if size == 0:
            size = _detectVintSize(n)

        if n >= 128**size - 1:
            with gil:
                raise OverflowError

        with gil:
            return ((o << (7*size)) | n).to_bytes(size, "big")

cpdef parseVint(bytes data):
    cdef unsigned int b = data[0]
    cdef unsigned long l = len(data)
    cdef unsigned long long k

    with nogil:
        k = _getVintSize(b)

        if l < k:
            with gil:
                raise UnexpectedEndOfData(
                    "Unexpected End of Data while scanning "
                    "variable-length integer.")

        with gil:
            return (data[:k], data[k:])

    raise ValueError("Invalid Vint.")


cpdef bytes readVint(file):
    cdef bytes b = file.read(1)

    if len(b) == 0:
        return b""

    cdef unsigned int x = b[0]
    cdef unsigned char k = _getVintSize(x)
    cdef bytes data = file.read(k - 1)

    if len(data) < k - 1:
        raise UnexpectedEndOfData(
            "Unexpected End of Data while scanning variable-length integer.")

    return b + data

cpdef str formatBytes(bytes data):
    return " ".join([f"{x:02X}" for x in data])

cpdef bytes peekVint(file, long long peekoffset=0):
    cdef unsigned long long o = file.tell()
    file.seek(peekoffset, 1)
    cdef bytes vint = readVint(file)
    file.seek(o)
    return vint


cdef class parseFile:
    cdef:
        object _file
        unsigned long long _startoffset
        unsigned long long _nextoffset
        long long _size

    def __cinit__(self, object file, long long size=-1):
        self._file = file
        self._nextoffset = self._startoffset = file.tell()
        self._size = size

    def __iter__(self):
        return self

    def __next__(self):
        cdef:
            bytes ebmlID
            bytes esize
            unsigned long long size

        if self._size >= 0 and self._nextoffset >= self._startoffset + self._size:
            raise StopIteration

        self._file.seek(self._nextoffset)
        ebmlID = readVint(self._file)

        if ebmlID == b"":
            raise StopIteration

        esize = readVint(self._file)
        size = fromVint(esize)
        val = (self._nextoffset, ebmlID, esize,
               self._nextoffset + len(ebmlID) + len(esize), size)
        self._nextoffset += len(ebmlID) + len(esize) + size

        if self._size >= 0 and self._nextoffset > self._startoffset + self._size:
            raise UnexpectedEndOfData("EBML Element extends past end of data.")

        return val

cdef class parseElements:
    cdef:
        object _data
        unsigned long long _offset
        long long _size

    def __cinit__(self, bytes data):
        self._data = data
        self._size = len(data)
        self._offset = 0

    def __iter__(self):
        return self

    def __next__(self):
        cdef:
            bytes ebmlID
            bytes esize
            unsigned long long size
            unsigned char vintsize
            unsigned char sizeoffset
            unsigned char dataoffset
            bytes data

        if self._offset >= self._size:
            raise StopIteration

        sizeoffset = _getVintSize(self._data[self._offset])
        ebmlID = self._data[self._offset: self._offset + sizeoffset]

        if len(ebmlID) < vintsize:
            raise UnexpectedEndOfData(
                "Unexpected End of Data while scanning variable-length integer.")

        vintsize = _getVintSize(self._data[self._offset + sizeoffset])
        esize = self._data[self._offset + sizeoffset:
                               self._offset + sizeoffset + vintsize]

        if len(esize) < vintsize:
            raise UnexpectedEndOfData(
                "Unexpected End of Data while scanning variable-length integer.")

        size = fromVint(esize)
        dataoffset = sizeoffset + vintsize

        data = self._data[self._offset + dataoffset: self._offset + dataoffset + size]

        if len(data) < size:
            raise UnexpectedEndOfData(
                "Unexpected End of Data while scanning data.")
            
        try:
            return (self._offset, ebmlID, vintsize, data)

        finally:
            self._offset += dataoffset + size


cdef class parseVints:
    cdef:
        bytes _data
        unsigned long long _size
        unsigned long long _offset

    def __cinit__(self, bytes data):
        self._data = data
        self._size = len(data)
        self._offset = 0

    def __iter__(self):
        return self

    def __next__(self):
        cdef:
            unsigned char size
            bytes vint
            cdef unsigned char b

        with nogil:
            if self._offset == self._size:
                with gil:
                    raise StopIteration

            with gil:
                b = self._data[self._offset]

            size = _getVintSize(b)

            if self._offset + size > self._size:
                with gil:
                    raise UnexpectedEndOfData()

            with gil:
                vint = self._data[self._offset: self._offset + size]

            self._offset += size

        return vint
