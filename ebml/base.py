#!/usr/bin/python3
import struct
import datetime
import binascii
import ebml.util
import ast
from itertools import count

try:
    import astor
except ModuleNotFoundError:
    """
    This module is used only for diagnostic purposes.
    This module can still be used without the astor module.
    """
    astor = None

import types
import sys
from ebml.exceptions import NoMatch, DecodeError, UnexpectedEndOfData, EncodeError

__all__ = ["Constant", "EBMLProperty", "EBMLList", "EBMLElement", "EBMLData", "EBMLString",
           "EBMLDateTime", "Void", "EBMLInteger", "EBMLFloat", "CRC32", "EBMLMasterElement"]

epoch = datetime.datetime(2001, 1, 1)

class Constant(object):
    def __init__(self, value):
        self.value = value

    def __get__(self, inst=None, cls=None):
        if inst is None:
            return self

        return self.value

class EBMLProperty(object):
    def __init__(self, attrname, cls, optional=False, sethook=None, default=None):
        self.attrname = attrname
        self._attrname = f"_{attrname}"
        self.cls = cls
        self.optional = optional
        self.default = default
        self._sethook = sethook

        if hasattr(cls, "data") and isinstance(cls.data, EBMLProperty):
            self._get = self.getdata
            self._set = self.setdata

        else:
            self._get = self.getobject
            self._set = self.setobject

    def __get__(self, inst=None, cls=None):
        if inst is None:
            return self

        return self._get(inst, cls)

    def getobject(self, inst, cls=None):
        try:
            value = getattr(inst, self._attrname)

        except AttributeError:
            if self.optional:
                return self.default

            raise

        if value is not None:
            return value

        return self.default

    def getdata(self, inst, cls=None):
        obj = self.getobject(inst, cls)

        if obj is not None:
            return obj.data

    def __set__(self, inst, value):
        return self._set(inst, value)

    def setobject(self, inst, value):
        if callable(self._sethook):
            value = self._sethook(inst, value)

        if hasattr(inst, "readonly") and inst.readonly:
            raise AttributeError("Cannot change attribute for read-only element.")

        if value is None and self.optional:
            setattr(inst, self._attrname, value)

        elif isinstance(value, self.cls):
            if isinstance(value, (EBMLElement, EBMLList)) and value.parent is not inst:
                value.parent = inst

            setattr(inst, self._attrname, value)

        elif issubclass(self.cls, (EBMLElement, EBMLList)):
            try:
                value = self.cls(value, parent=inst)

            except TypeError as exc:
                exc.args = (f"Invalid type {type(value).__name__} for '{self.attrname}' attribute of {type(inst).__name__} object.",)
                raise

        else:
            try:
                value = self.cls(value)

            except TypeError as exc:
                exc.args = (f"Invalid type {type(value).__name__} for '{self.attrname}' attribute of {type(inst).__name__} object.",)
                raise

        setattr(inst, self._attrname, value)

    def setdata(self, inst, value):
        if value is None and self.optional:
            return setattr(inst, self._attrname, value)

        if hasattr(inst, "readonly") and inst.readonly:
            raise AttributeError("Cannot change attribute for read-only element.")

        try:
            obj = self.getobject(inst)

        except AttributeError:
            obj = None

        if isinstance(obj, self.cls):
            obj.data = value


        else:
            self.setobject(inst, value)

    def __delete__(self, inst):
        if hasattr(inst, "readonly") and inst.readonly:
            raise AttributeError("Cannot change attribute for read-only element.")

        if not self.optional:
            raise AttributeError("Cannot delete required attribute.")

    def sethook(self, func):
        self._sethook = func
        return self

class EBMLList(list):
    itemclass = object

    @classmethod
    def makesubclass(cls, name, itemclass):
        return type(name, (cls,), {"itemclass": itemclass})

    def __init_subclass__(cls):
        if isinstance(cls.itemclass, type) and issubclass(cls.itemclass, EBMLData):
            cls.__init__ = cls.__init_data__
            cls.__getitem__ = cls.getdata
            cls.__setitem__ = cls.setdata
            cls.append = cls.appenddata
            cls.extend = cls.extenddata
            cls.insert = cls.insertdata
            cls.pop = cls.popdata
        else:
            cls.__init__ = cls.__init_object__
            cls.__setitem__ = cls.setobject
            cls.append = cls.appendobject
            cls.extend = cls.extendobject
            cls.insert = cls.insertobject

    def __init_data__(self, items=[], parent=None):
        self.parent = parent
        list.__init__(self, [self._castdata(item) for item in items])

    def __init_object__(self, items=[], parent=None):
        self.parent = parent

        for item in items:
            if not isinstance(item, self.itemclass):
                raise TypeError("Item must be of class {self.itemclass}, got {item.__class__.name} instead.")

        list.__init__(self, items)

    def _castdata(self, data):
        if isinstance(data, self.itemclass):
            data.parent = self.parent
            return data

        return self.itemclass(data=data, parent=self.parent)

    def copy(self, parent=None):
        cls = type(self)

        if hasattr(self.itemclass, "copy") and callable(self.itemclass.copy):
            new = cls([item.copy() for item in list.__iter__(self)], parent=parent)
            return new

        return cls(list.__iter__(self), parent=parent)

    def extenddata(self, items):
        self._checkReadOnly()

        list.extend(self, [self._castdata(item) for item in items])

    def extendobject(self, items):
        self._checkReadOnly()

        for item in items:
            if not isinstance(item, self.itemclass):
                raise TypeError("Item must be of class {self.itemclass}, got {item.__class__.name} instead.")

        list.extend(self, items)

    def appenddata(self, item):
        self._checkReadOnly()

        item = self._castdata(item)
        list.append(self, item)

    def appendobject(self, item):
        self._checkReadOnly()

        if not isinstance(item, self.itemclass):
            raise TypeError("Item must be of class {self.itemclass}, got {item.__class__.name} instead.")

        list.append(self, item)

    def insertdata(self, index, item):
        self._checkReadOnly()
        item = self._castdata(item)
        list.insert(self, index, item)

    def insertobject(self, index, item):
        self._checkReadOnly()

        if not isinstance(item, self.itemclass):
            raise TypeError("Item must be of class {self.itemclass}, got {item.__class__.name} instead.")

        list.insert(self, index, item)

    def getdata(self, index):
        item = list.__getitem__(self, index)
        return item.data

    getobject = list.__getitem__

    def popdata(self, index):
        self._checkReadOnly()
        item = self.popobject(index)
        return item.data

    def popobject(self, index):
        self._checkReadOnly()
        return list.pop(self, index)

    def setobject(self, index, item):
        self._checkReadOnly()
        item = self._castdata(item)
        list.__setitem__(self, index, item)

    def setdata(self, index, item):
        self._checkReadOnly()
        obj = self.getobject(index)
        obj.data = item

    def __delitem__(self, key):
        self._checkReadOnly()
        list.__delitem__(self, key)

    def remove(self, item):
        self._checkReadOnly()
        list.remove(self, item)

    def _checkReadOnly(self):
        if self.readonly:
            raise TypeError("List is read-only. Use .copy() method to create an editable copy.")

    @property
    def parent(self):
        return self._parent

    @parent.setter
    def parent(self, value):
        self._parent = value
        for item in self:
            item.parent = value

    @property
    def readonly(self):
        if isinstance(self.parent, EBMLElement):
            return self.parent.readonly

        return False

class EBMLElementMetaClass(type):
    def __new__(cls, name, bases, dct):
        cls._prepare(cls, bases, dct)
        return super().__new__(cls, name, bases, dct)

    def __getattribute__(cls, attrname):
        attr = super(EBMLElementMetaClass, cls).__getattribute__(attrname)

        if isinstance(attr, Constant):
            return attr.__get__(cls)

        if attrname == "ebmlID" and isinstance(attr, property):
            return attr.__get__(cls)

        return attr

    def __setattr__(cls, attrname, value):
        sup = super(EBMLElementMetaClass, cls)

        try:
            attr = sup.__getattribute__(attrname)
        except:
            return sup.__setattr__(attrname, value)

        attr = sup.__getattribute__(attrname)

        if isinstance(attr, Constant):
            raise AttributeError("Cannot set attribute. (Constant)")

        return sup.__setattr__(attrname, value)

    @staticmethod
    def _makeAttrAssign(name, attr, value, lineno=1, indent=""):
        name = ast.Name(id=name, lineno=lineno, col_offset=len(indent), ctx=ast.Load())
        attr = ast.Attribute(attr=attr, value=name, lineno=lineno, col_offset = len(f"{indent}{name}."), ctx=ast.Store())
        value = ast.Name(id=value, lineno=lineno, col_offset=len(f"{indent}{name}.{attr} = "), ctx=ast.Load())
        assign = ast.Assign(targets=[attr], value=value, lineno=lineno, col_offset=len(f"{indent}{name}.{attr} "))
        return assign

    @staticmethod
    def _makeIfNotNone(name, lineno=1, indent=""):
        left = ast.Name(id=name, lineno=lineno, col_offset=len(f"{indent}if "), ctx=ast.Load())
        right = ast.NameConstant(value=None, lineno=lineno, col_offset=len(f"{indent}if {name} is not "))
        isnot = ast.IsNot(lineno=lineno, col_offset=len(f"{indent}if {name}"))
        test = ast.Compare(left, [isnot], [right], lineno=lineno, col_offset=len(f"{indent}if {name} "))

        ifstmt = ast.If(test=test, body=[], orelse=[], lineno=lineno, col_offset=len(indent))
        return ifstmt

    @staticmethod
    def _makeFcnDef(name, args, defaults, body=[], lineno=1, indent=""):
        k = len(defaults)
        N = len(args)

        if k:
            required = args[:-k]
            optional = args[-k:]
        else:
            required = args
            optional = ()

        astargs = ast.arguments(args=[], vararg=None, defaults=[], kwonlyargs=[], kw_defaults=[], kwarg=None)

        s = f"{indent}def {name}("

        for j, arg in enumerate(["self"] + required, -1):
            astargs.args.append(ast.arg(arg=arg, lineno=lineno, col_offset=len(s), annotation=None))

            if j < N - 1:
                s += f"{arg}, "
            else:
                s += f"{arg})"

        for j, (arg, default) in enumerate(zip(optional, defaults), len(required)):
            astargs.args.append(ast.arg(arg=arg, lineno=lineno, col_offset=len(s), annotation=None))
            if default in (True, False, None):
                astargs.defaults.append(ast.NameConstant(value=default, lineno=1, col_offset=len(s + f"{arg}=")))

            elif isinstance(default, (int, float, complex)):
                astargs.defaults.append(ast.Num(value=default, lineno=1, col_offset=len(s + f"{arg}=")))

            #argdefs.append(default)

            if j < N - 1:
                s += f"{arg}={repr(default)}, "
            else:
                s += f"{arg}={repr(default)})"

        fcn = ast.FunctionDef(name=name, args=astargs, body=body,
                    decorator_list=[], annotation=None,
                    returns=None, lineno=1, col_offset=0)

        return fcn

    def _prepare(self, bases, dct):
        if "ebmlID" in dct and isinstance(dct["ebmlID"], bytes):
            dct["ebmlID"] = Constant(dct["ebmlID"])

        __init__body = []
        L = 2

        optional = []
        defaults = []
        args = []

        __ebmlproperties__ = dct.get("__ebmlproperties__")

        ancestorclasses = list(bases)

        while __ebmlproperties__ is None and len(ancestorclasses):
            ancestorclass = ancestorclasses.pop(0)

            if isinstance(ancestorclass, tuple):
                ancestorclasses.extend(ancestorclass)
                continue

            if not isinstance(ancestorclass, EBMLElementMetaClass):
                continue

            if hasattr(ancestorclass, "__ebmlproperties__"):
                __ebmlproperties__ = getattr(ancestorclass, "__ebmlproperties__")

        for prop in __ebmlproperties__:
            if isinstance(prop, EBMLProperty):
                if prop.optional:
                    optional.append(prop.attrname)
                    defaults.append(None)

                    if L > 1:
                        L += 1

                    ifstmt = self._makeIfNotNone(prop.attrname, L, "    ")
                    __init__body.append(ifstmt)
                    L += 1

                    assign = self._makeAttrAssign("self", prop.attrname, prop.attrname, L, "        ")
                    ifstmt.body.append(assign)
                    L += 1

                    if isinstance(prop.cls, EBMLElement):
                        assign = self._makeAttrAssign(f"_{prop.attrname}", "parent", "self", L, "        ")
                        ifstmt.body.append(assign)
                        L += 1

                    L += 1

                else:
                    args.append(prop.attrname)

                    assign = self._makeAttrAssign("self", prop.attrname, prop.attrname, L, "    ")
                    __init__body.append(assign)
                    L += 1

                    if isinstance(prop.cls, EBMLElement):
                        assign = self._makeAttrAssign(f"_{prop.attrname}", "parent", "self", L, "    ")
                        __init__body.body.append(assign)
                        L += 1

                if prop.attrname not in dct:
                    dct[prop.attrname] = prop

            else:
                raise TypeError("Expected 'property' object.")

        if not isinstance(dct.get("ebmlID"), Constant):
            args.append("ebmlID")
            assign = self._makeAttrAssign("self", "ebmlID", "ebmlID", L, "    ")
            __init__body.append(assign)
            L += 1

        assign = self._makeAttrAssign("self", "readonly", "readonly", L, "    ")
        __init__body.append(assign)
        L += 1

        if L > 1:
            L += 1

        ifstmt = self._makeIfNotNone("parent", L, "    ")
        __init__body.append(ifstmt)
        L += 1

        assign = self._makeAttrAssign("self", "parent", "parent", L, "        ")
        ifstmt.body.append(assign)
        L += 2

        optional.extend(["readonly", "parent"])
        defaults.extend([False, None])
        __init__ = self._makeFcnDef("__init__", args+optional, defaults, __init__body)

        if "__init__" not in dct:
            mod = ast.Module(body=[__init__])

            module_code = compile(mod, 'Automatically-generated __init__', 'exec')

            func_code = [c for c in module_code.co_consts
                if isinstance(c, types.CodeType)][0]

            dct["__init__"] = types.FunctionType(func_code, {"AttributeError": AttributeError},
                argdefs=tuple(defaults))

            if astor is not None:
                dct["__init__body__"] = astor.to_source(__init__)

class EBMLElement(object, metaclass=EBMLElementMetaClass):
    _parentEbmlID = None
    __ebmlproperties__ = ()

    def __init__(self, data, ebmlID=None, readonly=False, parent=None):
        if ebmlID is not None:
            self.ebmlID = ebmlID

        self.parent = parent
        self._init(data)
        self.readonly = readonly

    @property
    def body(self):
        if self.parent is not None:
            return self.parent.body

    def copy(self, parent=None):
        cls = type(self)
        new = cls.__new__(cls)
        kwargs = {}

        if hasattr(self, "__ebmlproperties__"):
            for prop in self.__ebmlproperties__:
                value = prop.__get__(self)

                if isinstance(value, (EBMLElement, EBMLList)):
                    value = value.copy(parent=new)
                kwargs[prop.attrname] = value

        if cls.ebmlID is None:
            kwargs["ebmlID"] = self.ebmlID

        new.__init__(**kwargs)
        return new

    @property
    def ebmlID(self):
        try:
            return self._ebmlID
        except AttributeError:
            return None

    @ebmlID.deleter
    def ebmlID(self):
        if self.readonly:
            raise AttributeError("Element is read-only. Use .copy() method to create an editable copy.")

        self._ebmlID = None

    @ebmlID.setter
    def ebmlID(self, value):
        if self.readonly:
            raise AttributeError("Element is read-only. Use .copy() method to create an editable copy.")

        if isinstance(value, bytes):
            k = len(value)

            if value[0] & (1 << (8 - k)) and (value[0] != 2**(8 - k) - 1 or value[1:] != b"\xff"*(k - 1)):
                self._ebmlID = value
                return
            else:
                raise ValueError(f"Not a valid EBML ID: {repr(value)}.")

        elif isinstance(value, int) and value >= 0:
            ebmlID = ebml.util.toVint(value)

            if isinstance(ebmlID, bytes):
                self._ebmlID = ebmlID
                return
            else:
                raise ValueError(f"Integer value too big.")

        elif value is None:
            self._ebmlID = None

        raise ValueError("Expecting bytes or int object.")

    @property
    def readonly(self):
        if hasattr(self, "_readonly") and self._readonly:
            return True
        #if hasattr(self, "_parent") and self.parent is not None and self.parent.readonly:
            #return True
        return False

    @readonly.setter
    def readonly(self, value):
        if self.readonly:
            raise AttributeError("Cannot change read-only status of read-only element. Use .copy() method.")
        self._readonly = bool(value)

    @property
    def parent(self):
        try:
            return self._parent
        except:
            return

    @parent.setter
    def parent(self, value):
        if self.readonly:
            raise AttributeError("Cannot set parent for read-only EBMLElement.")

        elif self._parentEbmlID is not None:
            if not isinstance(value, EBMLElement):
                raise ValueError("Parent must be an EBMLElement.")

            if isinstance(self._parentEbmlID, bytes) and value.ebmlID != self._parentEbmlID:
                raise ValueError("Parent must be an EBMLElement with EBML ID {self._parentEbmlID}.")

            elif isinstance(self._parentEbmlID, (tuple, list)) and value.ebmlID not in self._parentEbmlID:
                raise ValueError("Parent must be an EBMLElement with EBML ID {self._parentEbmlID}.")

        self._parent = value

    @classmethod
    def makesubclass(cls, clsName, **attributes):
        return type(clsName, (cls,), attributes)

    def size(self):
        """Returns total size (in bytes) of element, including header and size element"""
        contentsize = self._size()
        return len(self.ebmlID) + len(ebml.util.toVint(contentsize)) + contentsize

    def _size(self):
        """To be implemented in subclasses"""
        raise NotImplementedError()

    def toFile(self, file):
        contentsize = self._size()
        file.write(self.ebmlID)
        file.write(ebml.util.toVint(contentsize))
        self._toFile(file)

    def _toFile(self, file):
        """Override if desired."""
        file.write(self._toBytes())

    def toBytes(self):
        contentsize = self._size()
        data = self._toBytes()

        if len(data) != contentsize:
            raise EncodeError(f"{self}: Length of data ({len(data)}) does not match advertised length ({contentsize}).")

        return self.ebmlID + ebml.util.toVint(contentsize) + data

    def _toBytes(self, file):
        """To be implemented in subclasses"""
        raise NotImplementedError()

    @classmethod
    def fromFile(cls, file, parent=None):
        ebmlID = ebml.util.readVint(file)
        size = ebml.util.fromVint(ebml.util.readVint(file))

        if cls.ebmlID is not None:
            #print((ebmlID, cls.ebmlID))
            if ebmlID != cls.ebmlID:
                raise NoMatch

            return cls._fromFile(file, size, parent=parent)

        return cls._fromFile(file, size, ebmlID=ebmlID, parent=parent)

    @classmethod
    def _fromFile(cls, file, size, ebmlID=None, parent=None):
        """Override if desired."""
        data = file.read(size)

        if len(data) < size:
            raise UnexpectedEndOfData

        if ebmlID is not None:
            return cls._fromBytes(data, ebmlID=ebmlID, parent=parent)
        return cls._fromBytes(data, parent=parent)

    @staticmethod
    def _peekHeader(data):
        x = data[0]
        for j in range(1, 9):
            if x & (1 << (8 - j)):
                ebmlID = data[:j]
                break
        else:
            raise DecodeError(f"Invalid VINT for EBML ID: [{ebml.util.formatBytes(data[:8])}].")

        x = data[j]

        for k in range(1, 9):
            if x & (1 << (8 - k)):
                sizevint = data[j:j + k]
                break
        else:
            raise DecodeError(f"Invalid VINT for data size: [{ebml.util.formatBytes(data[j:j+8])}].")

        return (ebmlID, len(sizevint), ebml.util.fromVint(sizevint))

    @classmethod
    def fromBytes(cls, data, parent=None):
        ebmlID, sizesize, size = cls._peekHeader(data)

        if cls.ebmlID is not None and cls.ebmlID != ebmlID:
            h = "".join([f"[{x:02x}]" for x in ebmlID])
            raise NoMatch(f"Data does not begin with EBML ID {h}.")

        if len(data) != size + sizesize + len(ebmlID):
            raise DecodeError("Data length not consistent with encoded length.")

        if cls.ebmlID is None:
            return cls._fromBytes(data[sizesize + len(ebmlID):], ebmlID=ebmlID, parent=parent)
        return cls._fromBytes(data[sizesize + len(ebmlID):], parent=parent)

    @classmethod
    def _fromBytes(cls, data, ebmlID=None, parent=None):
        """To be implemented in subclasses"""
        raise NotImplementedError()

    def __repr__(self):
        params = []
        for prop in self.__ebmlproperties__:
            if prop.attrname in ("parent", "children"):
                continue

            try:
                value = prop.__get__(self)
            except AttributeError:
                value = None

            if value is None:
                continue

            if isinstance(type(value), EBMLMasterElementMetaClass):
                params.append(f"{prop.attrname}={value.__class__.__name__}(...)")

            elif isinstance(value, EBMLList):
                if isinstance(value.itemclass, tuple):
                    classes = "|".join(cls.__name__ for cls in value.itemclass)
                    params.append(f"{prop.attrname}=[({classes})(...), ...]")
                else:
                    params.append(f"{prop.attrname}=[{value.itemclass.__name__}(...), ...]")
            else:
                params.append(f"{prop.attrname}={value}")
        params = ", ".join(params)

        if len(params):
            return f"{self.__class__.__name__}(ebmlID=[{ebml.util.formatBytes(self.ebmlID)}], {params})"

        return f"{self.__class__.__name__}(ebmlID=[{ebml.util.formatBytes(self.ebmlID)}])"

class EBMLData(EBMLElement):
    __ebmlproperties__ = (EBMLProperty("data", bytes),)

    def _size(self):
        return len(self.data)

    def _toBytes(self):
        return self.data

    @classmethod
    def _fromBytes(cls, data, ebmlID=None, parent=None):
        if ebmlID is not None:
            return cls(data, ebmlID=ebmlID, parent=parent)
        return cls(data, parent=parent)

class EBMLString(EBMLData):
    __ebmlproperties__ = (EBMLProperty("data", str),)
    encoding = "utf8"

    def _size(self):
        return len(self.data.encode(self.encoding))

    def _toBytes(self):
        return self.data.encode(self.encoding)

    @classmethod
    def _fromBytes(cls, data, ebmlID=None, parent=None):
        if ebmlID is not None:
            return cls(data.decode(cls.encoding), ebmlID=ebmlID, parent=parent)
        return cls(data.decode(cls.encoding), parent=parent)

class EBMLDateTime(EBMLData):
    data = EBMLProperty("data", datetime.datetime)
    __ebmlproperties__ = (data,)
    
    @data.sethook
    def data(self, value):
        if isinstance(value, (int, float)):
            return epoch + datetime.timedelta(microseconds=value/1000)

        return value

    def to_int(self):
        return int(10**9*(self.data - epoch).total_seconds() + 0.5)

    def _toBytes(self):
        x = self.to_int()
        k = self._size()
        return x.to_bytes(k, "big")

    def _size(self):
        x = self.to_int()
        for k in range(1, 9):
            if -128*256**(k-1) <= x < 128*256**(k-1):
                return k

    @classmethod
    def _fromBytes(cls, data, ebmlID=None, parent=None):
        if ebmlID is not None:
            return cls(int.from_bytes(data, byteorder="big"), ebmlID=ebmlID, parent=parent)

        return cls(int.from_bytes(data, byteorder="big"), parent=parent)

class Void(EBMLElement):
    ebmlID = Constant(b"\xec")
    __ebmlproperties__ = (EBMLProperty("voidsize", int),)

    def _size(self):
        return self.voidsize

    @classmethod
    def _fromBytes(cls, data, ebmlID=None, parent=None):
        return cls(len(data), parent=parent)

    def _toBytes(self):
        return b"\x00"*self.voidsize

    def _toFile(self, file):
        try:
            file.seek(file.tell() + self.voidsize)
            return
        except:
            pass
        file.write(b"\x00"*self.voidsize)

    @classmethod
    def _fromFile(cls, file, size, ebmlID=None, parent=None):
        try:
            file.seek(file.tell() + size)
        except:
            file.read(size)
        return cls(size, parent=parent)

class EBMLInteger(EBMLData):
    data = EBMLProperty("data", int)
    signed = False
    __ebmlproperties__ = (data,)

    @data.sethook
    def data(self, value):
        if value < 0 and not self.signed:
            raise ValueError("Signed integers not supported.")
        return value

    def _toBytes(self):
        k = self._size()
        return self.data.to_bytes(k, "big")

    def _size(self):
        if self.signed:
            for k in count(1):
                if -128*256**(k-1) <= self.data < 128*256**(k-1):
                    return k
        else:
            for k in count(1):
                if self.data < 256**k:
                    return k

    @classmethod
    def _fromBytes(cls, data, ebmlID=None, parent=None):
        if cls.ebmlID is None:
            return cls(n, ebmlID=ebmlID, parent=parent)

        return cls(int.from_bytes(data, byteorder="big"), parent=parent)

    #@classmethod
    #def _fromBytes(cls, data, ebmlID=None, parent=None):
        #n = int.from_bytes(data, byteorder="big")
        #self = cls.__new__(cls)
        #self._data = n
        #self._parent = parent

        #if cls.ebmlID is None:
            #self._ebmlID = ebmlID

        #return self

class EBMLFloat(EBMLData):
    __ebmlproperties__ = (EBMLProperty("data", float),)

    def _toBytes(self):
        return struct.pack(">d", self.data)

    def _size(self):
        return 8

    @classmethod
    def _fromBytes(cls, data, ebmlID=None, parent=None):
        if len(data) == 4:
            x = struct.unpack(">f", data)[0]
        elif len(data) == 8:
            x = struct.unpack(">d", data)[0]
        else:
            raise DecodeError("Expected data size of either 4 or 8.")

        if ebmlID is not None:
            return cls(x, ebmlID=ebmlID, parent=parent)

        return cls(x, parent=parent)

class CRC32(EBMLData):
    ebmlID = b"\xbf"

class EBMLMasterElementMetaClass(EBMLElementMetaClass):
    def _prepare(cls, bases, dct):
        __ebmlproperties__ = dct.get("__ebmlproperties__", ())
        __ebmlchildren__ = dct.get("__ebmlchildren__", ())
        __ebmlpropertiesbyid__ = {}

        childTypes = {Void.ebmlID: Void, CRC32.ebmlID: CRC32}

        for prop in __ebmlchildren__:
            if isinstance(prop, EBMLProperty):
                if issubclass(prop.cls, EBMLElement):
                    if prop.cls.ebmlID is not None and prop.cls.ebmlID not in childTypes:
                        childTypes[prop.cls.ebmlID] = prop.cls
                        __ebmlpropertiesbyid__[prop.cls.ebmlID] = prop

                elif issubclass(prop.cls, EBMLList):
                    if isinstance(prop.cls.itemclass, tuple):
                        for cls in prop.cls.itemclass:
                            if cls.ebmlID is not None and cls.ebmlID not in childTypes:
                                childTypes[cls.ebmlID] = cls
                                __ebmlpropertiesbyid__[cls.ebmlID] = prop

                    else:
                        if prop.cls.itemclass.ebmlID not in childTypes:
                            childTypes[prop.cls.itemclass.ebmlID] = prop.cls.itemclass
                            __ebmlpropertiesbyid__[prop.cls.itemclass.ebmlID] = prop

                else:
                    raise ValueError("What gives?")

            else:
                raise TypeError("Expected 'EBMLProperty' object.")

        if dct.get("allowunknown", False):
            ebmlchildren = EBMLList.makesubclass("EBMLChildList", tuple(childTypes.values()) + (EBMLData,))
        else:
            ebmlchildren = EBMLList.makesubclass("EBMLChildList", tuple(childTypes.values()))

        dct["__ebmlproperties__"] = tuple(__ebmlchildren__) + tuple(__ebmlproperties__) + (EBMLProperty("children", ebmlchildren, optional=True),)
        dct["__ebmlpropertiesbyid__"] = __ebmlpropertiesbyid__
        

        if "_childTypes" in dct:
            dct["_childTypes"].update(childTypes)
        else:
            dct["_childTypes"] = childTypes

        EBMLElementMetaClass._prepare(cls, bases, dct)

class EBMLMasterElement(EBMLElement, metaclass=EBMLMasterElementMetaClass):
    __ebmlchildren__ = ()
    allowunknown = False

    def iterchildren(self):
        if self.children is not None:
            for child in self.children:
                yield child

        else:
            for prop in self.__ebmlchildren__:
                child = prop.getobject(self)
                if isinstance(child, EBMLList):
                    for item in list.__iter__(child):
                        yield item
                elif isinstance(child, EBMLElement):
                    yield child

    @EBMLElement.readonly.setter
    def readonly(self, value):
        if self.readonly:
            raise AttributeError("Cannot change read-only status of read-only element. Use .copy() method.")
        self._readonly = bool(value)

        if self.children is not None:
            for child in list.__iter__(self.children):
                child.readonly = value

    def _size(self):
        childrensizes = [child.size() for child in self.iterchildren()]
        return sum(childrensizes)

    def _toBytes(self):
        data = b""

        for child in self.iterchildren():
            data += child.toBytes()

        return data

    def _decodeData(self, data):
        children = []

        while len(data):
            ebmlID, sizesize, size = self._peekHeader(data)

            if self.allowunknown:
                childcls = self._childTypes.get(ebmlID, EBMLData)

            else:
                childcls = self._childTypes.get(ebmlID)

            if childcls is None:
                raise DecodeError(f"Unrecognized EBML ID {ebml.util.formatBytes(ebmlID)}.")

            child = childcls._fromBytes(data[len(ebmlID) + sizesize:len(ebmlID) + sizesize + size], parent=self)
            children.append(child)

            if ebmlID in self.__ebmlpropertiesbyid__:
                prop = self.__ebmlpropertiesbyid__[ebmlID]

                if issubclass(prop.cls, EBMLList):
                    if not hasattr(self, f"_{prop.attrname}"):
                        prop.__set__(self, [])

                    L = prop.__get__(self)
                    L.append(child)

                else:
                    if hasattr(self, f"_{prop.attrname}"):
                        raise TypeError(f"Too many child elements of type '{prop.cls.__name__}' provided.")

                    prop.__set__(self, child)

            elif not isinstance(child, (Void, CRC32)) and not self.allowunknown:
                raise TypeError(f"Unexpected type '{child.__class__.__name__}' for type '{self.__name__}'.")

            else:
                if not isinstance(child, (Void, CRC32)):
                    raise TypeError(f"Unexpected type '{child.__class__.__name__}' for type '{self.__name__}'.")

            data = data[len(ebmlID) + sizesize + size:]

        missing = []

        for prop in self.__ebmlchildren__:
            if not hasattr(self, f"_{prop.attrname}"):
                if not prop.optional:
                    missing.append(prop)
                else:
                    prop.__set__(self, None)

        l = [prop.cls.itemclass.__name__ if issubclass(prop.cls, EBMLList) else prop.cls.__name for prop in missing]

        if len(missing) == 1:
            raise DecodeError(f"Missing required element: {l[0]}.")
        elif len(missing) == 2:
            raise DecodeError(f"Missing required elements: {l[0]} and {l[1]}.")
        elif len(missing) > 2:
            raise DecodeError(f"Missing required elements: {', '.join(l[:-1])}, and {l[-1]}.")

        self.children = children

        if type(self).ebmlID is None:
            self.ebmlID = ebmlID

    @classmethod
    def _fromBytes(cls, data, ebmlID=None, parent=None):
        self = cls.__new__(cls)
        self.parent = parent

        self._decodeData(data)

        return self

    def copy(self, parent=None):
        cls = type(self)
        new = cls.__new__(cls)
        kwargs = {}

        if hasattr(self, "__ebmlchildren__"):
            for prop in self.__ebmlchildren__:
                value = prop.__get__(self)

                if isinstance(value, (EBMLElement, EBMLList)):
                    value = value.copy(parent=new)

                kwargs[prop.attrname] = value

        if cls.ebmlID is None:
            kwargs["ebmlID"] = self.ebmlID

        new.__init__(**kwargs)
        return new
