from ebml.base import EBMLMasterElement, EBMLElement, Void, EBMLData
from ebml.head import EBMLHead
from ebml.util import readVint, fromVint, toVint, formatBytes, peekVint
from ebml.exceptions import UnexpectedEndOfData
import io
import threading

from ebml.exceptions import ReadError, WriteError

class EBMLBody(EBMLMasterElement):
    """
    This element will only read/write child elements from/to a file rather than store them in memory.
    Only addresses for elements in the file will be stored.
    """

    allowunknown = True

    def __init__(self, file, ebmlID=None, parent=None):
        self._file = file
        self.lock = threading.RLock()

        if ebmlID is not None:
            self.ebmlID = ebmlID

        self.parent = parent
        self._knownChildren = {}
        self._modified = False

        if "r" in file.mode:
            try:
                self._init_read()

            except UnexpectedEndOfData:
                if not self._file.writable():
                    raise

                self._init_write()

        else:
            self._init_write()

    def _size(self):
        return self._contentssize

    def _toBytes(self):
        raise NotImplementedError("Use self.writeChildElement(...) and self.removeChildElement(...) to modify file.")

    def _init_write(self):
        self._file.write(self.ebmlID)

        self._sizeOffset = self._file.tell()
        self._sizesize = 8
        self._file.write(((1 << (7*self._sizesize + 1)) - 1).to_bytes(self._sizesize, byteorder="big"))

        self._contentssize = 0
        self._contentsOffset = self._file.tell()

    def _init_read(self):
        ebmlID = readVint(self._file)

        if self.ebmlID is not None:
            if self.ebmlID != ebmlID:
                raise ReadError(f"Incorrect EBML ID found. Expected '{formatBytes(self.ebmlID)},' got '{formatBytes(ebmlID)}' instead.")
        else:
            self.ebmlID = ebmlID

        self._sizeOffset = self._file.tell()
        size = readVint(self._file)
        self._sizesize = len(size)
        self._contentssize = fromVint(size)
        self._contentsOffset = self._file.tell()

        if self._file.writable():
            self.seek(0)
            self.scan()
            self.seek(0)

    def _writeVoid(self, size):
        for k in range(1, 9):
            if size - 1 - k < 128**k - 1:
                break

        self._file.write(b"\xec")
        self._file.write(toVint(size - 1 - k, k))

    @property
    def body(self):
        return self

    def close(self):
        """Writes Void elements in unallocated space and closes file."""
        if self._modified and self._file.writable():
            L = sorted(self._knownChildren.items())
            for (s1, e1), (s2, e2) in zip([(0, 0)] + L[:-1], L):
                if e1 < s2:
                    self.seek(e1)
                    self._writeVoid(s2 - e1)

            if len(L):
                (s, e) = max(L)

            else:
                e = 0

            self.seek(e)
            self._file.truncate()
            self.seek(-self._sizesize)
            self._file.write(toVint(e, self._sizesize))
        self._file.close()

    def __del__(self):
        if not self._file.closed:
            self.close()

    def seek(self, offset, whence=0):
        """Seeks file relative to start of offset."""
        if whence == 1:
            return self._file.seek(offset + self._contentsOffset, whence)
        elif whence == 2:
            return self._file.seek(offset + self._contentsOffset + self._contentssize)
        return self._file.seek(offset + self._contentsOffset, whence)

    def tell(self):
        """Returns file offset relative to start of offset."""
        return self._file.tell() - self._contentsOffset

    def writeChildElement(self, child):
        """
        Write a child element at the current file offset. Raises an exception if a 
        collision with a sibling or a gap of 1 byte (Void requires two bytes) is detected. 
        """

        offset = self.tell()
        siblingsbefore = {(s, e) for (s, e) in self._knownChildren.items() if s <= offset}
        siblingsafter = {(s, e) for (s, e) in self._knownChildren.items() if s > offset}

        if len(siblingsbefore):
            (s, e) = max(siblingsbefore)
            if offset < e:
                raise WriteError(f"Writing element at offset {offset} collides with sibling at offset {s} (end offset {e}).")
            if offset == e + 1:
                raise WriteError(f"Element needs to start immediately after, or at least two bytes past the end of sibling at offset {s}.")

        childsize = child.size()

        if len(siblingsafter):
            (s, e) = min(siblingsafter)

            if offset + childsize > s:
                raise WriteError(f"Writing element at offset {offset} collides with sibling at offset {s} (end offset {e}).")
            if offset + childsize == s - 1:
                raise WriteError(f"Element needs to end immediately before, or at least two bytes before the start of sibling at offset {s}.")

        if offset + childsize > 2**(7*self._sizesize) - 2:
            raise WriteError(f"Element extends past maximum possible element size.")

        child.toFile(self._file)

        if not child.readonly:
            child.readonly = True

        self._knownChildren[offset] = self.tell()
        self._contentssize = max(self._contentssize, self.tell())
        self._modified = True
        return offset

    def deleteChildElement(self, offset):
        """
        deleteChildElement(offset)

        Deletes reference to child element at specified offset. Space will become
        allocated by a Void element upon file being closed.
        """

        if not self._file.writable():
            raise io.UnsupportedOperation("write")

        del self._knownChildren[offset]

        children = list(self._knownChildren.items())

        if len(children):
            (s, self._contentssize) = max(children)

        else:
            self._contentssize = 0

        self._modified = True

    def readElement(self, withclass, parent=None, ignore=()):
        """
        readElement(withclass, parent=None, ignore=())

        Read element on behalf of a descendent element at the current file offset.

        Returns element of a class specified by 'withclass' (can be either a class, list,
        tuple, or dict with EBML IDs as keys).

        Advances read position and returns None if it detects an EBML ID specified
        in 'ignore'.
        """

        if isinstance(withclass, type) and issubclass(withclass, EBMLElement):
            withclass = {withclass.ebmlID: withclass}

        elif isinstance(withclass, (list, tuple)):
            withclass = {cls.ebmlID: cls for cls in withclass}

        ignore = tuple(item.ebmlID if isinstance(item, EBMLElement) else item
                       for item in ignore)

        offset = self.tell()

        if offset >= self._contentssize or offset < 0:
            return

        ebmlID = peekVint(self._file)
        size = peekVint(self._file, len(ebmlID))

        if ebmlID in ignore or ebmlID == Void.ebmlID:
            self._file.seek(len(ebmlID) + len(size) + fromVint(size), 1)
            return

        if ebmlID not in withclass:
            raise ReadError(f"Unrecognized EBML ID [{formatBytes(ebmlID)}] at offet {offset} in body, (file offset {offset + self._contentsOffset}).")

        child = withclass[ebmlID].fromFile(self._file, parent=parent)

        if parent is self:
            child.offsetInParent = offset
            child.dataOffsetInParent = offset + len(ebmlID) + len(size)

        child.readonly = True

        return child

    def readChildElement(self):
        """Reads a child element at current offset."""
        offset = self.tell()

        if offset >= self._contentssize or offset < 0:
            return None

        siblingsbefore = {(s, e) for (s, e) in self._knownChildren.items() if s <= offset}

        if len(siblingsbefore):
            (s, e) = max(siblingsbefore)

            if s < offset < e:
                raise ReadError(f"Offset {offset} is in the middle of a known child at offset {s}.")

        try:
            child = self.readElement(self._childTypes, parent=self)

        except ReadError:
            if self.allowunknown:
                child = EBMLData.fromFile(self._file, parent=self)

            else:
                raise

        self._knownChildren[offset] = self.tell()
        return child

    def flush(self):
        self._file.flush()

    def scan(self, until=None):
        """
        scan(until=None)

        Scans body for child elements from the last known child before current offset until
        the end of the body, or 'until.'
        """
        offset = self.tell()

        childrenbefore = {(s, e) for (s, e) in self._knownChildren.items() if s <= offset}
        if len(childrenbefore):
            (s, e) = max(childrenbefore)
            self.seek(e)
        else:
            self.seek(0)

        if until is None:
            until = self._contentssize

        while offset < until:
            with self.lock:
                self.seek(offset)
                ebmlID = peekVint(self._file)
                size = peekVint(self._file, len(ebmlID))

            if ebmlID != Void.ebmlID:
                self._knownChildren[offset] = offset + len(ebmlID) + len(size) + fromVint(size)

            offset += len(ebmlID) + len(size) + fromVint(size)

    @classmethod
    def _fromBytes(cls, data, ebmlID=None, parent=None):
        raise NotImplementedError("Use self.readChildElement()) to readfile.")

    @property
    def contentsOffset(self):
        return self._contentsOffset

    @property
    def contentsSize(self):
        return self._contentssize



class EBMLDocument(object):
    def __init__(self, file, mode="r", bodycls=EBMLBody):
        if "b" not in mode:
            mode += "b"

        self._file = open(file, mode)
        self._bodycls = bodycls

        if "r" in mode:
            self._init_read()

        elif "w" in mode:
            self._init_write()

    def _init_read(self):
        """
        This should be overridden in subclasses if you are looking to handle specific document types.
        """
        self.head = EBMLHead.fromFile(self._file)
        self.body = self._bodycls(self._file)

    def _init_write(self):
        """
        This should be overridden in subclasses if you are looking to handle specific document types.
        """
        self.head = None
        self.body = None
        

    def writeEBMLHead(self, ebmlHead):
        if hasattr(self, "head") and self.head is not None:
            raise WriteError("EBML Header already exists.")

        ebmlHead.toFile(self._file)
        self.head = ebmlHead
        ebmlHead.readonly = True

    def beginWriteEBMLBody(self, ebmlID=None):
        if not hasattr(self, "head") or self.head is None:
            raise WriteError("EBML Header does not exist.")

        if hasattr(self, "body") and self.body is not None:
            raise WriteError("EBML Body already exists.")

        if ebmlID is not None:
            self.body = self._bodycls(self._file, ebmlID=ebmlID)

        else:
            self.body = self._bodycls(self._file)

    @property
    def writeChildElement(self):
        return self.body.writeChildElement

    @property
    def readChildElement(self):
        return self.body.readChildElement

    @property
    def deleteChildElement(self):
        return self.body.deleteChildElement

    @property
    def seek(self):
        return self.body.seek

    @property
    def tell(self):
        return self.body.tell

    @property
    def close(self):
        return self.body.close

    @property
    def fileSize(self):
        return self.body.contentsOffset + self.body.contentsSize
