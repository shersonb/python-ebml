from .base import (EBMLMasterElement, EBMLElement, Void, CRC32, EBMLData,
                   EBMLProperty)
from .vint import parseFile, readVint, fromVint, toVint, detectVintSize
from .util import (_fallocate, NoInterrupt, FALLOC_FL_KEEP_SIZE,
                   FALLOC_FL_PUNCH_HOLE, FALLOC_FL_COLLAPSE_RANGE,
                   FALLOC_FL_INSERT_RANGE)
from .exceptions import *
from threading import RLock as Lock
import weakref
import signal
import os
import bisect
import time
from . import _file

def isfile(value):
    return (hasattr(value, "seekable") and callable(value.seekable) and value.seekable()
            and hasattr(value, "seek") and callable(value.seek)
            and hasattr(value, "mode") and "b" in value.mode
            and hasattr(value, "write") and callable(value.write)
            and hasattr(value, "read") and callable(value.read))

class EBMLMasterElementInFile(EBMLElement):
    # TODO:
    # * Allow instances to be created without being immediately written to
    # file or parent element, holding data in memory.
    # * Allow instances to be detached from parent, preserving data.

    __ebmlchildren__ = ()
    _childTypes = {Void.ebmlID: Void, CRC32.ebmlID: CRC32}
    allowunknown = True
    __ebmlproperties__ = (
            EBMLProperty("offsetInParent", int, optional=True),
            EBMLProperty("dataSize", int, optional=True)
        )

    def __init_subclass__(cls):
        cls._childTypes.update({ccls.ebmlID: ccls for ccls in cls.__ebmlchildren__})
        cls.__init__ = EBMLMasterElementInFile.__init__

    def _getChildCls(self, ebmlID):
        if self.allowunknown:
            return self._childTypes.get(ebmlID, EBMLData)

        else:
            return self._childTypes.get(ebmlID)

    def __init__(self, parent, offset=0, size=0, sizeLength=8, ebmlID=None):
        if ebmlID is not None:
            self.ebmlID = ebmlID

        self._init(parent, offset, size, sizeLength)

        with self.lock:
            if isinstance(parent, EBMLMasterElementInFile):
                parent.addChildElement(self, offset)

            parent.seek(offset)
            self.file.write(self.ebmlID)
            self.file.write(toVint(size, sizeLength))

            if size > 0:
                self._writeVoid(0, size)

            if isfile(parent):
                parent.seek(offset + len(self.ebmlID) + sizeLength + size)
                parent.truncate()

    @property
    def bsize(self):
        """Block size (determined by file system)."""
        return self.root._bsize

    def _init(self, parent, offset, size, sizeLength):
        if size >= 2**(7*sizeLength) - 1:
            raise ValueError(f"Size of {size} too large for sizeLength {sizeLength}.")

        self.parent = parent

        if isfile(parent) and hasattr(parent, "name"):
            self._bsize = os.statvfs(parent.name).f_bsize

        else:
            self._bsize = None

        self._sizeLength = sizeLength
        self.dataSize = size
        self.offsetInParent = offset
        self._children = {}
        self._childoffsets = []
        self._pos = 0

    def _writeVoid(self, offset, size):
        for k in range(1, 9):
            if size - 1 - k < 128**k - 1:
                break

        self.file.seek(self.dataOffsetInFile + offset)
        self.file.write(b"\xec")
        self.file.write(toVint(size - 1 - k, k))

    @property
    def lock(self):
        if isinstance(self.parent, EBMLMasterElementInFile):
            return self.parent.lock

        return self._lock

    @property
    def file(self):
        if isinstance(self._parent, EBMLMasterElementInFile):
            return self._parent.file

        return self._parent

    @property
    def root(self):
        if isinstance(self._parent, EBMLMasterElementInFile):
            return self._parent.root

        return self

    @property
    def parent(self):
        return self._parent

    @parent.setter
    def parent(self, value):
        if isinstance(value, EBMLMasterElementInFile):
            self._lock = None

        elif isfile(value):
            self._lock = Lock()

        else:
            raise TypeError(
                "Parent must either be instance of EBMLMasterElementInFile, "
                "or a seekable file-like object opened in binary mode.")

        self._parent = value

    def _destroy(self):
        self._parent = None
        self._lock = None

        for (ebmlID, ref, endOffset) in self._children.values():
            if not isinstance(ref, weakref.ref):
                continue

            obj = ref()

            if isinstance(obj, EBMLMasterElementInFile):
                obj._destroy()

    def size(self):
        return self.dataOffset + self.dataSize

    @property
    def dataOffset(self):
        return len(self.ebmlID) + self._sizeLength

    @property
    def offsetInFile(self):
        if isinstance(self.parent, EBMLMasterElementInFile):
            return self.parent.dataOffsetInFile + self.offsetInParent

        return self.offsetInParent

    @property
    def dataOffsetInFile(self):
        return self.offsetInFile + len(self.ebmlID) + self._sizeLength

    @property
    def dataOffsetInParent(self):
        return self.offsetInParent + len(self.ebmlID) + self._sizeLength

    def _repr_add(self):
        return (f"offsetInFile={self.offsetInFile}")

    def getChildElement(self, offset):
        """Returns child element at 'offset'."""

        with self.lock:
            return self._getChildElement(offset)

    def _getChildElement(self, offset):
        child = self._getExistingChildElement(offset)

        if child is None:
            ebmlID, ref, endOffset = self._children[offset]
            child = self._readChildElement(offset)
            self._children[offset] = (ebmlID, weakref.ref(child), endOffset)
            return child

        return child

    def _getExistingChildElement(self, offset):
        ebmlID, ref, endOffset = self._children[offset]

        if isinstance(ref, weakref.ref):
            return ref()

    def iterChildren(self):
        """
        Return iterator that yields all child elements.

        Notice: Iterator will follow child elements around if move operations
        occur.
        """

        with self.lock:
            offset = self._childoffsets[0]
            child = self._getChildElement(offset)

        yield child

        while True:
            with self.lock:
                offset = self._nextChild(child.offsetInParent)

                if offset is None:
                    break

                child = self._getChildElement(offset)

            yield child

    def _iterChildren(self):
        for offset in self._childoffsets:
            yield self._getChildElement(offset)

    def scan(self):
        with self.lock:
            self._scan()

    def _scan(self):
        self._children = {}
        self._childoffsets = []

        self.file.seek(self.dataOffsetInFile)

        for (offsetInFile, ebmlID, vsize,
             dataOffsetInFile, isize) in parseFile(
                 self.file, self.dataSize):

            if ebmlID != Void.ebmlID:
                self._scanchild(
                    offsetInFile - self.dataOffsetInFile, ebmlID, vsize,
                    dataOffsetInFile - self.dataOffsetInFile, isize)

    def _scan(self):
        _file._scan(self)

    def _scanchild(self, offset, ebmlID, vsize, dataoffset, isize):
        self._children[offset] = (
            ebmlID, None, dataoffset + isize)
        # bisect.insort(self._childoffsets, offset)

        # It is safe to assume that this function is being called on
        # increasing values of offset, so we will go with the less-
        # expensive append operation.
        self._childoffsets.append(offset)

    def _scanchild(self, offset, ebmlID, vsize, dataoffset, isize):
        _file._scanchild(self, offset, ebmlID, vsize, dataoffset, isize)

    def _readChildElement(self, offset=-1):
        with self.lock:
            if offset < 0:
                offset = self._pos

            ebmlID, ref, endOffset = self._children[offset]
            childcls = self._getChildCls(ebmlID)
            self.seek(offset)
            self._pos = endOffset
            child = childcls.fromFile(self.file, parent=self)
            child.offsetInParent = offset

            if not isinstance(child, EBMLMasterElementInFile):
                child.readonly = True

            return child

    def _canAddChildElement(self, child, offset):
        if offset < 0:
            raise WriteError(f"Invalid offset: {offset}.", self, offset)

        prevChild = self._prevChild(offset)
        nextChild = self._nextChild(offset - 1)

        if prevChild is not None:
            (_, _, e) = self._children[prevChild]
 
            if offset < e:
                raise WriteError(
                    f"Writing child at offset {offset} collides"
                    f"with sibling at offset {prevChild} (end offset {e}).",
                    self, offset)

            if offset == e + 1:
                raise WriteError(
                    "Child needs to start immediately after, or at least two "
                    f"bytes past the end of sibling at offset {prevChild} "
                    f" (end offset {e}).", self, offset)

        elif offset == 1:
            raise WriteError("Cannot add child at offset 1.", self, offset)

        childsize = child.size()

        if nextChild is not None:
            if offset + childsize > nextChild:
                raise WriteError(
                    f"Writing element at offset {offset} with size "
                    f"{childsize} collides with "
                    f"sibling at offset {nextChild}.", self, offset)

            if offset + childsize == nextChild - 1:
                raise WriteError(
                    "Child needs to end immediately before, or at least "
                    f"two bytes before the start of sibling at offset {s}.",
                    self, offset)

        elif offset + childsize > self.dataSize:
            raise WriteError(f"Child will extend past element size.",
                             self, offset)

        elif offset + childsize == self.dataSize - 1:
            raise WriteError(
                "Child must not end one byte before end of element.",
                self, offset)

    def canAddChildElement(self, child, offset):
        with self.lock:
            try:
                self._canAddChildElement(child, offset)

            except WriteError:
                return False

            return True

    def addChildElement(self, child, offset):
        """
        Insert child element at 'offset'.

        To make space, see insertRange(start, end), resize(newsize),
        and moveChildElement(offset, newoffset).
        """

        with self.lock:
            self._canAddChildElement(child, offset)
            return self._addChildElement(child, offset)

    def _addChildElement(self, child, offset):
        childsize = child.size()
        prevChild = self._prevChild(offset)
        nextChild = self._nextChild(offset - 1)

        if prevChild is not None:
            (_, _, e) = self._children[prevChild]

        else:
            e = 0

        if nextChild is not None:
            s = nextChild

        else:
            s = self.dataSize

        with NoInterrupt():
            if offset > e:
                self._writeVoid(e, offset - e)


            if s > offset + childsize:
                self._writeVoid(offset + childsize, s - offset - childsize)

            if not isinstance(child, EBMLMasterElementInFile):
                self.file.seek(self.dataOffsetInFile + offset)
                child.toFile(self.file)
                child.parent = self
                child.offsetInParent = offset
                child.readonly = True

            self._children[offset] = (child.ebmlID, weakref.ref(child),
                                    offset + childsize)
            bisect.insort(self._childoffsets, offset)

            self.file.flush()

        return offset + childsize

    def removeChildElement(self, offset):
        """
        Remove child element at 'offset'.

        To free up deallocate the freed space, use
        punchHole(start, end).
        """

        with self.lock:
            self._removeChildElement(offset)

    def _removeChildElement(self, offset):
        ebmlID, ref, _ = self._children[offset]

        prevChild = self._prevChild(offset)
        nextChild = self._nextChild(offset)

        if prevChild is not None:
            (_, _, e) = self._children[prevChild]

        else:
            e = 0

        if nextChild is not None:
            s = nextChild

        else:
            s = self.dataSize

        with NoInterrupt():
            if s > e:
                self._writeVoid(e, s - e)

            del self._children[offset]
            self._childoffsets.remove(offset)

            obj = ref() if isinstance(ref, weakref.ref) else None

            if isinstance(obj, EBMLMasterElementInFile):
                obj._destroy()

            self.file.flush()

    def canMoveChildElement(self, offset, newoffset):
        with self.lock:
            try:
                self._canMoveChildElement(offset, newoffset)

            except WriteError:
                return False

            return True

    def _canMoveChildElement(self, offset, newoffset):
        if newoffset < 0:
            raise WriteError(f"Invalid offset: {newoffset}.",
                             self, newoffset)

        ebmlID, ref, endoffset = self._children[offset]

        prevChild = self._prevChild(offset)
        nextChild = self._nextChild(offset - 1)

        if prevChild is not None:
            (_, _, e) = self._children[prevChild]

            if newoffset < e:
                raise WriteError(
                    f"Writing child at offset {newoffset} collides"
                    f"with sibling at offset {prevChild} (end offset {e}).",
                    self, newoffset)

            if newoffset == e + 1:
                raise WriteError(
                    "Child needs to start immediately after, or at least "
                    f"two bytes past the end of sibling at offset {s}"
                    f" (end offset {e}).", self, newoffset)

        elif newoffset == 1:
            raise WriteError("Cannot add child at offset 1.", self, newoffset)

        childsize = endoffset - offset

        if nextChild is not None:
            s = nextChild

            if newoffset + childsize > s:
                raise WriteError(
                    f"Writing element at offset {newoffset} with size {size} "
                    f"collides with sibling at offset {s} (end offset {e}).",
                    self, newoffset)

            if newoffset + childsize == s - 1:
                raise WriteError(
                    "Child needs to end immediately before, or at least "
                    f"two bytes before the start of sibling at offset {s}.",
                    self, newoffset)

        elif newoffset + childsize > self.dataSize:
            raise WriteError(f"Child will extend past element size.",
                             self, newoffset)

        elif newoffset + childsize == self.dataSize - 1:
            raise WriteError(
                "Child must not end one byte before end of element.",
                self, newoffset)

    def moveChildElement(self, offset, newoffset):
        """
        Moves child element (physically).

        To move child elements logically, but not physically, see
        insertRange(start, end) and collapseRange(start, end).
        (Note: Unlike moveChildElement, those methods cannot change
        the logical order of child elements.)
        """

        with self.lock:
            self._canMoveChildElement(offset, newoffset)
            self._moveChildElement(offset, newoffset)

    def _moveChildElement(self, offset, newoffset):
        ebmlID, ref, endoffset = self._children[offset]
        childsize = endoffset - offset

        blksize = self.bsize

        if newoffset < offset:
            iterator = zip(range(offset, endoffset, blksize),
                        range(newoffset, newoffset + childsize, blksize))

        else:
            iterator = zip(
                range(endoffset - blksize, offset - blksize, -blksize),
                range(newoffset + childsize - blksize,
                        newoffset - blksize, -blksize))

        prevChildOld = self._prevChild(offset)
        nextChildOld = self._nextChild(offset)

        if prevChildOld is not None:
            (_, _, e1) = self._children[prevChildOld]

        else:
            e1 = 0

        if nextChildOld is not None:
            s1 = nextChildOld

        else:
            s1 = self.dataSize

        prevChildNew = self._prevChild(newoffset)
        nextChildNew = self._nextChild(newoffset)

        if prevChildNew == offset:
            prevChildNew = self._prevChild(offset)

        if nextChildNew == offset:
            nextChildNew = self._nextChild(offset)

        if prevChildNew is not None:
            (_, _, e1) = self._children[prevChildNew]

        else:
            e1 = 0

        if nextChildOld is not None:
            s1 = nextChildNew

        else:
            s1 = self.dataSize

        with NoInterrupt():
            for o1, o2 in iterator:
                size = min(blksize, endoffset - o1)

                (o1, size, o2) = max([
                    (o1, size, o2),
                    (offset, size - (offset - o1), o2 + (offset - o1))])

                self.seek(o1)
                data = self.file.read(size)
                self.seek(o2)
                self.file.write(data)

            if not (e1 <= newoffset < s1):
                self._writeVoid(e1, s1 - e1)

            if newoffset > e1:
                self._writeVoid(e1, newoffset - e1)

            if newoffset + childsize < s1:
                self._writeVoid(newoffset + childsize, s1 - (newoffset + childsize))

            del self._children[offset]
            self._childoffsets.remove(offset)

            self._children[newoffset] = (ebmlID, ref, newoffset + childsize)
            bisect.insort(self._childoffsets, newoffset)

            obj = ref() if ref is not None else ref

            if isinstance(obj, EBMLMasterElementInFile):
                obj.offsetInParent = newoffset

            elif isinstance(obj, EBMLElement):
                ro = obj.readonly
                obj._readonly = False
                obj.offsetInParent = newoffset
                obj._readonly = ro

            self.file.flush()

    def startOfFirstChild(self):
        """
        Returns offset of first child element.

        If no children elements exist, will return dataSize.
        """

        with self.lock:
            return self._startOfFirstChild()

    def _startOfFirstChild(self):
        if len(self._childoffsets):
            return self._childoffsets[-1]

    def endOfLastChild(self):
        """
        Returns end offset of last child element.

        If no children elements exist, will return 0.
        """

        with self.lock:
            return self._endOfLastChild()

    def _endOfLastChild(self):
        if len(self._childoffsets):
            lastchild = self._childoffsets[-1]
            (_, _, endOffset) = self._children[lastchild]
            return endOffset

        return 0

    def nextChild(self, offset, strict=True):
        with self.lock:
            return self._nextChild(offset, strict)

    def _nextChild(self, offset, strict=True):
        if not strict and offset in self._childoffsets:
            return offset

        k = bisect.bisect(self._childoffsets, offset)

        if k < len(self._childoffsets):
            return self._childoffsets[k]

    def prevChild(self, offset, strict=True):
        """
        Find offset of child that starts before 'offset', or return None
        if none exists.
        """

        with self.lock:
            return self._prevChild(offset, strict)

    def _prevChild(self, offset, strict=True):
        if not strict and offset in self._childoffsets:
            return offset

        k = bisect.bisect_left(self._childoffsets, offset) - 1

        if k >= 0:
            return self._childoffsets[k]

    def canResizeChild(self, offset, newsize):
        with self.lock:
            child = self._getChildElement(offset)

            if not isinstance(child, EBMLMasterElementInFile):
                return False

            try:
                self._canResizeChild(child, newsize)

            except ResizeError:
                return False

            return True

    def _canResizeChild(self, child, newsize):
        nextChild = self._nextChild(child.offsetInParent)
        endOffset = child.dataOffsetInParent + newsize

        if nextChild is not None:
            if endOffset > nextChild or endOffset == nextChild - 1:
                raise ResizeError(f"Cannot resize to size {newsize} "
                                  f"(next sibling starts at {nextChild}).")

        elif endOffset > self.dataSize or endOffset == self.dataSize - 1:
            raise ResizeError(f"Cannot resize to size {newsize} "
                              f"(parent size is {self.dataSize}).")

    def canResize(self, newsize):
        with self.lock:
            try:
                self._canResize(newsize)

            except ResizeError:
                return False

            return True

    def _canResize(self, newsize):
        if len(self._childoffsets):
            lastChild = self._childoffsets[-1]
            ebmlID, ref, endOffset = self._children[lastChild]

            if newsize < endOffset or newsize == endOffset + 1:
                raise ResizeError(f"Cannot resize to size {newsize} "
                                  f"(last child ends at {endOffset}).")

        elif newsize == 1:
            raise ResizeError(f"Cannot resize to size {newsize}.")

        if isinstance(self.parent, EBMLMasterElementInFile):
            self.parent._canResizeChild(self, newsize)

    def resize(self, newsize):
        """
        Resize element by changing the size data in the file.

        To resize element by using fallocate to insert or remove blocks from
        file, use insertRange(offset, size) and collapseRange(offset, size)
        instead, using 
        """
        with self.lock:
            self._canResize(newsize)
            self._resize(newsize)

    def _resize(self, newsize):
        offset = self.offsetInParent

        if len(self._childoffsets):
            lastChild = self._childoffsets[-1]
            ebmlID, ref, lastChildEnd = self._children[lastChild]

        elif newsize > 0:
            lastChildEnd = 0

        if isinstance(self.parent, EBMLMasterElementInFile):
            endOffset = self.dataOffsetInParent + newsize

            # Write void after element
            nextSibling = self.parent._nextChild(self.offsetInParent)

            if nextSibling is not None:
                o = nextSibling

            else:
                o = self.parent.dataSize

        with NoInterrupt():
            # Set element size in header
            self.seek(-self._sizeLength)
            self.file.write(toVint(newsize, self._sizeLength))

            # Write void at end
            if newsize > lastChildEnd:
                self._writeVoid(lastChildEnd, newsize - lastChildEnd)

            if isinstance(self.parent, EBMLMasterElementInFile):
                # Write void after element
                if o > endOffset:
                    self.parent._writeVoid(endOffset, o - endOffset)

                ebmlID, ref, _ = self.parent._children[offset]
                self.parent._children[offset] = (ebmlID, ref, endOffset)

            elif isfile(self.parent):
                # Truncate file
                self.seek(newsize)
                self.file.truncate()

            self.dataSize = newsize
            self.file.flush()

    def findFree(self, size, start=0):
        with self.lock:
            return self._findFree(size, start)

    def _findFree(self, size, start=0):
        if start == 1:
            start = 2

        for o in self._childoffsets:
            (ebmlID, ref, endOffset) = self._children[o]

            if start == endOffset + 1:
                start += 1

            if start > o:
                continue

            s = o - start

            if s == size or s >= size + 2:
                return start

            start = endOffset

        s = self.dataSize - start

        if s == size or s >= size + 2:
            return start

    def tell(self):
        """Returns file offset relative to start of offset."""
        return self.file.tell() - self.dataOffsetInFile

    def seek(self, offset):
        self.file.seek(offset + self.dataOffsetInFile)

    @classmethod
    def fromFile(cls, file, parent=None):
        offset = file.tell()
        ebmlID = readVint(file)
        size = readVint(file)

        if cls.ebmlID is not None:
            if ebmlID != cls.ebmlID:
                raise NoMatch

        self = cls.__new__(cls)

        if cls.ebmlID is None:
            self.ebmlID = ebmlID

        if isinstance(parent, EBMLMasterElementInFile):
            if parent.file is not file:
                raise ValueError()

            offsetInParent = offset - parent.dataOffsetInFile
            self._init(parent, offsetInParent, fromVint(size), len(size))

        else:
            offsetInParent = offset
            self._init(file, offsetInParent, fromVint(size), len(size))

        self.scan()
        return self

    def canPunchHole(self, offset, size):
        """Checks to see if punching hole can result in corrupting file."""
        with self.lock:
            try:
                self._canPunchHole(offset, size)

            except WriteError:
                return False

        return True

    def _canPunchHole(self, offset, size):
        prev = self._prevChild(offset)
        _, _, prevEnd = self._children.get(prev, (None, None, 0))

        if prevEnd > offset:
            raise WriteError(
                f"Punching hole at offset {offset} with size {size} will "
                f"collide with child at offset {prev}, end offset {prevEnd}.",
                self, offset)

        elif offset + size > self.dataSize:
            raise WriteError(
                f"Punching hole at offset {offset} with size {size} will "
                f"overrun element size {self.dataSize}.", self, offset)

        nextChild = self._nextChild(offset)

        if nextChild is not None:
            if offset + size > nextChild:
                raise WriteError(
                    f"Punching hole at offset {offset} with size {size} will "
                    f"collide with child at offset {nextChild}.", self, offset)

    def punchHole(self, offset, size):
        """Sparsify blocks via fallocate()."""

        with self.lock:
            self._canPunchHole(offset, size)
            self._punchHole(offset, size)

    def _punchHole(self, offset, size):
        self.file.flush()
        _fallocate(self.file, FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE,
                   self.dataOffsetInFile + offset, size)

        prevChild = self.prevChild(offset)
        _, _, prevEnd = self._children.get(prev, (None, None, 0))

        nextChild = self.nextChild(offset)

        if nextChild is None:
            nextChild = self.dataSize

        self._writeVoid(prevEnd, nextChild - prevEnd)

    def canCollapseRange(self, offset, size):
        with self.lock:
            try:
                self._canCollapseRange(offset, size)

            except WriteError:
                return False

        return True

    def _canCollapseRange(self, offset, size):
        prev = self._prevChild(offset)
        _, _, prevEnd = self._children.get(prev, (None, None, 0))

        if prevEnd > offset:
            raise WriteError(
                f"Collapsing range at offset {offset} with size {size} will "
                f"collide with child at offset {prev}, end offset {prevEnd}.",
                self, offset)

        elif offset + size > self.dataSize:
            raise WriteError(
                f"Collapsing range at offset {offset} with size {size} will "
                f"overrun element size {self.dataSize}.", self, offset)

        if self.dataSize - prevEnd - size == 1:
            raise WriteError(
                f"Collapsing range at offset {offset} with size {size} will "
                f"leave a space of one byte between child at offset "
                f"{prev}, end offset {prevEnd}, and end of element "
                f"{self.dataSize}.", self, offset)

        nextChild = self._nextChild(offset)

        if nextChild is not None:
            if offset + size > nextChild:
                raise WriteError(
                    f"Collapsing range at offset {offset} with size {size} will "
                    f"collide with child at offset {nextChild}.", self, offset)

            if nextChild - prevEnd - size == 1:
                raise WriteError(
                    f"Collapsing range at offset {offset} with size {size} will "
                    f"leave a space of one byte between child at offset "
                    f"{prev}, end offset {prevEnd}, "
                    f"and child at offset {nextChild}.", self, offset)

    def collapseRange(self, offset, size):
        """Remove blocks via fallocate()."""
        with self.lock:
            self._canCollapseRange(offset, size)
            self._collapseRange(offset, size)

    def _collapseRange(self, offset, size):
        prev = self._prevChild(offset)
        _, _, prevEnd = self._children.get(prev, (None, None, 0))
        nextChild = self._nextChild(offset)

        if nextChild is None:
            nextChild = self.dataSize

        self.file.flush()
        eof = self.file.seek(0, 2)
        self.seek(offset)

        with NoInterrupt():
            if self.dataOffsetInFile + offset + size >= eof:
                self.seek(offset)
                self.file.truncate()

            else:
                _fallocate(self.file, FALLOC_FL_COLLAPSE_RANGE,
                        self.dataOffsetInFile + offset, size)

            if nextChild - prevEnd - size >= 2:
                self._writeVoid(prevEnd, nextChild - prevEnd - size)

            self._rangeCollapsed(offset, size)

    def _rangeCollapsed(self, offset, size):
        K = bisect.bisect_left(self._childoffsets, offset)

        for k in range(K, len(self._childoffsets)):
            o = self._childoffsets[k]
            (ebmlID, ref, e) = self._children[o]
            self._children[o - size] = (ebmlID, ref, e - size)
            del self._children[o]
            self._childoffsets[k] = o - size

            # Update .offsetInParent attribute in any child element
            if isinstance(ref, weakref.ref):
                obj = ref()

                if isinstance(obj, EBMLMasterElementInFile):
                    obj.offsetInParent -= size

                elif isinstance(obj, EBMLElement):
                    ro = obj._readonly
                    obj._readonly = False
                    obj.offsetInParent -= size
                    obj._readonly = ro


        self.dataSize -= size
        self.seek(-self._sizeLength)
        self.file.write(toVint(self.dataSize, self._sizeLength))
        self.file.flush()

        if isinstance(self.parent, EBMLMasterElementInFile):
            (ebmlID, ref, endOffset) = self.parent._children[
                self.offsetInParent]
            self.parent._rangeCollapsed(offset + self.dataOffsetInParent, size)
            self.parent._children[self.offsetInParent] = (
                ebmlID, ref, endOffset - size)

    def canInsertRange(self, offset, size):
        with self.lock:
            try:
                self._canInsertRange(offset, size)

            except WriteError:
                return False

            except ValueError:
                return False

        return True

    def _canInsertRange(self, offset, size):
        if not (0 <= offset <= self.dataSize):
            raise ValueError(f"Offset {offset} outside range of element "
                             f"(0 — {self.dataSize}).")

        # Check to make sure inserting sectors into this element will not
        # cause the new sizes of this element, along with each of its
        # ancestors, will not overrun their vint widths.

        element = self

        while isinstance(element, EBMLMasterElementInFile):
            if detectVintSize(element.dataSize + size) > element._sizeLength:
                raise WriteError(
                    f"Element with size width {element._sizeLength} does "
                    f"not support  resizing to {element.dataSize + size}.",
                    self, offset)

            element = element.parent

        # Check to see if we are attempting to insert space into a child
        # element.

        prevChild = self.prevChild(offset)
        _, _, prevEnd = self._children.get(prevChild, (None, None, 0))

        if prevEnd > offset:
            raise WriteError(
                f"Inserting range at offset {offset} with size {size} will "
                f"collide with child at offset {prev}, end offset {prevEnd}.",
                self, offset)

    def insertRange(self, offset, size):
        """Insert blocks via fallocate()."""
        with self.lock:
            self._canInsertRange(offset, size)
            self._insertRange(offset, size)

    def _insertRange(self, offset, size):
        prevChild = self._prevChild(offset)
        _, _, prevEnd = self._children.get(prevChild, (None, None, 0))

        nextChild = self._nextChild(offset-1)

        if nextChild is None:
            nextChild = self.dataSize

        eof = self.file.seek(0, 2)
        self.seek(offset)

        with NoInterrupt():
            if self.dataOffsetInFile + offset >= eof:
                self.seek(offset + size)
                self.file.truncate()

            else:
                _fallocate(self.file, FALLOC_FL_INSERT_RANGE,
                        self.dataOffsetInFile + offset, size)

            self._writeVoid(prevEnd, nextChild - prevEnd + size)
            self._rangeInserted(offset, size)

    def _rangeInserted(self, offset, size):
        K = bisect.bisect_left(self._childoffsets, offset)

        for k in reversed(range(K, len(self._childoffsets))):
            o = self._childoffsets[k]
            (ebmlID, ref, e) = self._children[o]
            self._children[o + size] = (ebmlID, ref, e + size)
            del self._children[o]
            self._childoffsets[k] = o + size

            # Update .offsetInParent attribute in any child element
            if isinstance(ref, weakref.ref):
                obj = ref()

                if isinstance(obj, EBMLMasterElementInFile):
                    obj.offsetInParent += size

                elif isinstance(obj, EBMLElement):
                    ro = obj._readonly
                    obj._readonly = False
                    obj.offsetInParent += size
                    obj._readonly = ro

        self.dataSize += size
        self.seek(-self._sizeLength)
        self.file.write(toVint(self.dataSize, self._sizeLength))
        self.file.flush()

        if isinstance(self.parent, EBMLMasterElementInFile):
            (ebmlID, ref, endOffset) = self.parent._children[
                self.offsetInParent]
            self.parent._rangeInserted(offset + self.dataOffsetInParent, size)
            self.parent._children[self.offsetInParent] = (
                ebmlID, ref, endOffset + size)

    @staticmethod
    def _offsetsMoved(o, offset, size):
        if isinstance(o, int):
            return o if o < offset else o + size

    def findBoundary(self, start=0):
        with self.lock:
            return self._findBoundary(start)

    def _findBoundary(self, start=0):
        """
        Find offset that corresponsds to block boundary in the file.
        """
        q, r = divmod(self.dataOffsetInFile + start, self.bsize)

        if r:
            return (q + 1)*self.bsize - self.dataOffsetInFile

        return start

    def rfindBoundary(self, start=0):
        """
        Find offset that corresponsds to block boundary in the file.
        (Reversed)
        """
        with self.lock:
            return self._rfindBoundary(start)

    def _rfindBoundary(self, start=0):
        q, r = divmod(self.dataOffsetInFile + start, self.bsize)

        if r:
            return q*self.bsize - self.dataOffsetInFile

        return start

    def findOpenBoundary(self, start=0):
        """
        Finds an offset on a block boundary where one can insert a child
        element.
        """

        with self.lock:
            return self._findOpenBoundary(start)

    def _findOpenBoundary(self, start=0):
        bsize = self.bsize

        while start <= self.dataSize:
            q, r = divmod(self.dataOffsetInFile + start, bsize)

            if r:
                start = (q + 1)*bsize - self.dataOffsetInFile

            prevChild = self._prevChild(start)

            if prevChild is not None:
                (_, _, prevChildEnd) = self._children[prevChild]

                if start < prevChildEnd:
                    start = prevChildEnd
                    continue

                if start == prevChildEnd + 1:
                    start += bsize
                    continue

            if start <= self.dataSize:
                return start

    def rfindOpenBoundary(self, start=None):
        """
        Finds an offset on a block boundary where one can insert a child
        element (Reverse).
        """

        with self.lock:
            return self._rfindOpenBoundary(start)

    def _rfindOpenBoundary(self, start=None):
        bsize = self.bsize

        if start is None:
            q, r = divmod(self.dataOffsetInFile + self.endOfLastChild(),
                          bsize)

            if r and (q + 1)*bsize - self.dataOffsetInFile:
                start = min(self.dataSize,
                            (q + 1)*bsize - self.dataOffsetInFile)

            else:
                start = self.endOfLastChild()

        while start >= 0:
            q, r = divmod(self.dataOffsetInFile + start, bsize)

            if r:
                start = q*bsize - self.dataOffsetInFile

            prevChild = self._prevChild(start)

            if prevChild is not None:
                (_, _, prevChildEnd) = self._children[prevChild]

                if (start < prevChildEnd
                        or start == prevChildEnd + 1):
                    start = prevChild
                    continue

            if start >= 0:
                return start

    def childIsElementInFile(self, offset):
        """
        Check if child element at 'offset' is an instance of
        EBMLMasterElementInFile.
        """

        with self.lock:
            return self._childIsElementInFile(offset)

    def _childIsElementInFile(self, offset):
        (ebmlID, _, _) = self._children[offset]
        cls = self._childTypes.get(ebmlID)

        return (isinstance(cls, type)
                and issubclass(cls, EBMLMasterElementInFile))

    def tryCollapseRange(self, start, end):
        """
        Attempt to collapse range (fallocate), suppressing WriteError,
        returning True or False, depending on success. Will round start
        and end to block boundaries.
        """

        with self.lock:
            return self._tryCollapseRange(start, end)

    def _tryCollapseRange(self, start, end):
        start = self._findOpenBoundary(start)
        end = self._rfindOpenBoundary(end)

        if start < end:
            try:
                self._canCollapseRange(start, end - start)

            except WriteError:
                return False

            self._collapseRange(start, end - start)

        return True

    def tryMoveChildElement(self, offset, newoffset):
        """
        Attempt to move element, suppressing WriteError, returning
        True or False, depending on success.
        """

        with self.lock:
            return self._tryMoveChildElement(offset, newoffset)

    def _tryMoveChildElement(self, offset, newoffset):
        try:
            self._canMoveChildElement(offset, newoffset)

        except WriteError:
            return False

        self._moveChildElement(offset, newoffset)
        return True

    def quickTrim(self, maxsize=4*1024**2):
        """
        Make element smaller by moving only small elements and
        removing blocks from file.
        """

        with self.lock:
            self._quickTrim(maxsize)

    def _quickTrim(self, maxsize=4*1024**2):
        for k in range(len(self._childoffsets)):
            offset = self._childoffsets[k]
            (ebmlID, _, endOffset) = self._children[offset]

            if k > 0:
                prevChild = self._childoffsets[k-1]
                (prevEbmlID, _, prevEnd) = self._children[prevChild]

            else:
                prevChild = None
                prevEnd = 0
                prevEbmlID = None

            if self._childIsElementInFile(offset):
                obj = self._getChildElement(offset)
                obj._quickTrim(maxsize)
                self._tryCollapseRange(prevEnd, offset)

            elif endOffset - offset <= maxsize:
                if k == 0 and 0 < offset:
                    self._tryMoveChildElement(offset, 0)

                elif (prevChild is not None
                      and self._childIsElementInFile(prevChild)):
                    newoffset = self._findOpenBoundary(prevEnd)

                    if newOffset < offset:
                        self._tryMoveChildElement(offset, newoffset)

                elif prevEnd < offset:
                    self._tryMoveChildElement(offset, prevEnd)

            else:
                self._tryCollapseRange(prevEnd, offset)

        if len(self._childoffsets):
            offset = self._childoffsets[-1]
            (_, _, offset) = self._children[offset]
            offset = self._findOpenBoundary(offset)

        else:
            offset = self._findOpenBoundary()

        if offset is not None and offset < self.dataSize:
            try:
                self._canResize(offset)

            except WriteError:
                print(self)
                pass

            else:
                self._resize(offset)
