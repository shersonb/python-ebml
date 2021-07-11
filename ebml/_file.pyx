from .base import Void
from .vint import parseFile

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

def _scanchild(self, offset, ebmlID, vsize, dataoffset, isize):
    self._children[offset] = (
        ebmlID, None, dataoffset + isize)
    # bisect.insort(self._childoffsets, offset)

    # It is safe to assume that this function is being called on
    # increasing values of offset, so we will go with the less-
    # expensive append operation.
    self._childoffsets.append(offset)
