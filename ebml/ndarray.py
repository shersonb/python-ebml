import numpy
from ebml.base import EBMLInteger, EBMLString, EBMLData, EBMLMasterElement, EBMLList, EBMLProperty
from ebml.util import toVint, fromVint, parseVints, parseElements

class TypeString(EBMLString):
    ebmlID = b"\x91"

class Align(EBMLInteger):
    ebmlID = b"\x92"

class Copy(EBMLInteger):
    ebmlID = b"\x93"

class ByteOrder(EBMLString):
    ebmlID = b"\x94"

class Shape(EBMLData):
    ebmlID = b"\x95"
    __ebmlproperties__ = (EBMLProperty("data", tuple),)

    @classmethod
    def _fromBytes(cls, data, parent=None):
        return cls(tuple(fromVint(b) for b in parseVints(data)), parent=parent)

    def _toBytes(self):
        return b"".join(toVint(k) for k in self.data)

    def _size(self):
        return sum(len(toVint(k)) for k in self.data)

class FieldName(EBMLString):
    ebmlID = b"\xa1"

class FieldTitle(EBMLString):
    ebmlID = b"\xa2"

class FieldOffset(EBMLInteger):
    ebmlID = b"\xa3"

class Field(EBMLMasterElement):
    ebmlID = b"\xa0"

class Fields(EBMLList):
    itemclass = Field
    
class ItemSize(EBMLInteger):
    ebmlID = b"\x96"

class Alignment(EBMLInteger):
    ebmlID = b"\x97"

class Flags(EBMLInteger):
    ebmlID = b"\x98"

class DType(EBMLMasterElement):
    ebmlID = b"\x90"

    @classmethod
    def fromNumpy(cls, dtype, parent=None):
        if not isinstance(dtype, numpy.dtype):
            raise TypeError(f"Expected numpy.dtype, got {dtype.__class__.__name__} instead.")

        _, (typeString, align, copy), (_, byteOrder, baseshape,
                                       names, fields, itemsize, alignment, flags) = dtype.__reduce__()

        if itemsize < 0:
            itemsize = None

        if alignment < 0:
            alignment = None

        if baseshape is not None:
            base, shape = baseshape
            base = cls.fromNumpy(base)
            shape = Shape(shape)

        else:
            base = shape = None

        fieldlist = []

        if names:
            for fieldName in names:
                field = fields[fieldName]
                if len(field) == 2:
                    fielddtype, offset = field
                    fieldTitle = None

                else:
                    fielddtype, fieldOffset, fieldTitle = field

                fieldlist.append(Field(fieldName, cls.fromNumpy(fielddtype), fieldOffset, fieldTitle))

        return cls(typeString, align, copy, byteOrder, flags, base, shape, fieldlist, itemsize, alignment, parent=parent)

    def toNumpy(self):
        if self.fields:
            names = tuple(field.fieldName for field in self.fields)
            fields = {}

            for field in self.fields:
                if field.fieldTitle:
                    t = (field.dtype.toNumpy(), field.fieldOffset, field.fieldTitle)
                    fields[field.fieldTitle] = t

                fields[field.fieldName] = t

        else:
            names = None
            fields = None

        if self.base:
            baseshape = (self.base.toNumpy(), self.shape)

        else:
            baseshape = None

        itemsize = self.itemSize if self.itemSize is not None else -1
        alignment = self.alignment if self.alignment is not None else -1

        dtype = numpy.dtype(self.typeString, self.align, self.copy_)
        dtype.__setstate__((3, self.byteOrder, baseshape,
                                       names, fields, itemsize, alignment, self.flags))
        return dtype

Field.__ebmlchildren__ = (
        EBMLProperty("fieldName", FieldName),
        EBMLProperty("fieldTitle", FieldTitle, optional=True),
        EBMLProperty("dtype", DType),
        EBMLProperty("fieldOffset", FieldOffset),
    )

Field._prepare()
Field._generate__init__()

DType.__ebmlchildren__ = (
        EBMLProperty("typeString", TypeString),
        EBMLProperty("align", Align),
        EBMLProperty("copy_", Copy),
        EBMLProperty("byteOrder", ByteOrder),
        EBMLProperty("base", DType, optional=True),
        EBMLProperty("shape", Shape, optional=True),
        EBMLProperty("fields", Fields, optional=True),
        EBMLProperty("itemSize", ItemSize, optional=True),
        EBMLProperty("alignment", Alignment, optional=True),
        EBMLProperty("flags", Flags),
    )

DType._prepare()
DType._generate__init__()

class EBMLArrayData(EBMLData):
    ebmlID = b"\xb0"

class EBMLNDArray(EBMLData):
    data = EBMLProperty("data", numpy.ndarray)
    __ebmlproperties__ = (data,)

    @classmethod
    def _fromBytes(cls, data, ebmlID=None, parent=None):
        dtype = None
        shape = None
        arraydata = None

        for (offset, childEbmlID, k, data) in parseElements(data):
            if childEbmlID == EBMLArrayData.ebmlID:
                arraydata = data

            elif childEbmlID == Shape.ebmlID:
                shape = Shape._fromBytes(data)

            elif childEbmlID == DType.ebmlID:
                dtype = DType._fromBytes(data)

        if ebmlID is not None:
            return cls(numpy.frombuffer(arraydata, dtype=dtype.toNumpy()).reshape(shape.data), ebmlID=ebmlID, parent=parent)

        return cls(numpy.frombuffer(arraydata, dtype=dtype.toNumpy()).reshape(shape.data), parent=parent)

    @property
    def dtype(self):
        return DType.fromNumpy(self.data.dtype, parent=self)

    @property
    def shape(self):
        return Shape(self.data.shape, parent=self)

    def _toBytes(self):
        return self.dtype.toBytes() + self.shape.toBytes() + EBMLArrayData(bytes(self.data)).toBytes()

    def _size(self):
        datasize = self.data.size*self.data.itemsize
        return self.dtype.size() + self.shape.size() + len(EBMLArrayData.ebmlID) + len(toVint(datasize)) + datasize
