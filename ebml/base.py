#!/usr/bin/python3
import struct
import datetime
import binascii
import ebml.util
import ast
from itertools import count
import weakref
import sys
import io

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

    @property
    def __doc__(self):
        if isinstance(self.cls, type) and issubclass(self.cls, EBMLList):
            if isinstance(self.cls.itemclass, tuple):
                types = []

                for cls in self.cls.itemclass:
                    if cls.__module__ == "builtins":
                        types.append(cls.__name__)

                    else:
                        types.append(f"{cls.__module__}.{cls.__name__}")

                if len(types) == 1:
                    typestring = f"List of {types[-1]} objects"

                elif len(types) == 2:
                    typestring = "List of objects of type " + " or ".join(types)

                else:
                    typestring = "List of objects of type " + ", ".join(types[:-1]) + ", or " + types[-1]

            elif self.cls.itemclass.__module__ == "builtins":
                typestring = f"List of {self.cls.itemclass.__name__} objects"

            else:
                typestring = f"List of {self.cls.itemclass.__module__}.{self.cls.itemclass.__name__} objects"

        elif isinstance(self.cls, tuple):
            types = []

            for cls in self.cls:
                if cls.__module__ == "builtins":
                    types.append(cls.__name__)

                else:
                    types.append(f"{cls.__module__}.{cls.__name__}")

            if len(types) == 1:
                typestring = f"{types[-1]} object"

            elif len(types) == 2:
                typestring = "object of type " + " or ".join(types)

            else:
                typestring = "object of type " + ", ".join(types[:-1]) + ", or " + types[-1]

        elif self.cls.__module__ == "builtins":
            typestring = f"{self.cls.__name__} object"

        else:
            typestring = f"{self.cls.__module__}.{self.cls.__name__} object"

        if self.optional:
            return f"{typestring} (optional)"

        return f"{typestring} (required)"

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

        elif isinstance(self.cls, type) and issubclass(self.cls, (EBMLElement, EBMLList)):
            value = self.cls(value, parent=inst)

        else:
            value = self.cls(value)

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
            cls.__iter__ = cls.__iter_data__
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
        list.__init__(self, [self._wrapitem(item) for item in items])

    def __init_object__(self, items=[], parent=None):
        self.parent = parent

        for item in items:
            if not isinstance(item, self.itemclass):
                raise TypeError(f"Item must be of class {self.itemclass.__name__}, got {item.__class__.__name__} instead.")

            if isinstance(item, EBMLElement):
                item.parent = parent

        list.__init__(self, items)

    def __iter_data__(self):
        for obj in list.__iter__(self):
            yield obj.data

    def _wrapitem(self, data):
        if isinstance(data, self.itemclass):
            data.parent = self.parent
            return data

        return self.itemclass(data=data, parent=self.parent)

    def copy(self, parent=None):
        cls = type(self)
        newitems = [item.copy() if hasattr(item, "copy") and callable(item.copy)
                    else item
                    for item in self]

        return cls(newitems, parent=parent)

    def extenddata(self, items):
        self._checkReadOnly()

        list.extend(self, [self._wrapitem(item) for item in items])

    def extendobject(self, items):
        self._checkReadOnly()

        for item in items:
            if not isinstance(item, self.itemclass):
                raise TypeError(f"Item must be of class {self.itemclass}, got {item.__class__.__name__} instead.")

            if isinstance(item, EBMLElement):
                item.parent = self.parent

        list.extend(self, items)

    def appenddata(self, item):
        self._checkReadOnly()

        item = self._wrapitem(item)
        list.append(self, item)

    def appendobject(self, item):
        self._checkReadOnly()

        if not isinstance(item, self.itemclass):
            raise TypeError(f"Item must be of class {self.itemclass}, got {item.__class__.__name__} instead.")

        if isinstance(item, EBMLElement):
            item.parent = self.parent

        list.append(self, item)

    def insertdata(self, index, item):
        self._checkReadOnly()
        item = self._wrapitem(item)
        list.insert(self, index, item)

    def insertobject(self, index, item):
        self._checkReadOnly()

        if not isinstance(item, self.itemclass):
            raise TypeError(f"Item must be of class {self.itemclass}, got {item.__class__.__name__} instead.")

        if isinstance(item, EBMLElement):
            item.parent = self.parent

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

        if isinstance(index, slice):
            item = map(self._wrapitem, item)

        else:
            item = self._wrapitem(item)

        if isinstance(item, EBMLElement):
            item.parent = self.parent

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
        if isinstance(self._parent, weakref.ref):
            return self._parent()

        return self._parent

    @parent.setter
    def parent(self, value):
        try:
            self._parent = weakref.ref(value)

        except TypeError:
            self._parent = value

        for item in self:
            if isinstance(item, EBMLElement):
                item.parent = value

    @property
    def readonly(self):
        if isinstance(self.parent, EBMLElement):
            return self.parent.readonly

        return False

class EBMLElementMetaClass(type):
    def __new__(cls, name, bases, dct):
        if "_childTypes" not in dct:
            dct["_childTypes"] = {}

        newcls = super().__new__(cls, name, bases, dct)
        newcls._prepare()
        return newcls

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

            if j < N - 1:
                s += f"{arg}={repr(default)}, "
            else:
                s += f"{arg}={repr(default)})"

        fcn = ast.FunctionDef(name=name, args=astargs, body=body,
                    decorator_list=[], annotation=None,
                    returns=None, lineno=1, col_offset=0)

        return fcn

    def _generate__init__(cls):
        optional = []
        defaults = []
        required = []
        __init__body = []
        __ebmlproperties__ = cls.__ebmlproperties__
        L = 2

        for prop in __ebmlproperties__:
            if prop.optional:
                optional.append(prop.attrname)
                defaults.append(None)

                if L > 1:
                    L += 1

                ifstmt = cls._makeIfNotNone(prop.attrname, L, "    ")
                __init__body.append(ifstmt)
                L += 1

                assign = cls._makeAttrAssign("self", prop.attrname, prop.attrname, L, "        ")
                ifstmt.body.append(assign)
                L += 1

                if isinstance(prop.cls, EBMLElement):
                    assign = cls._makeAttrAssign(f"_{prop.attrname}", "parent", "self", L, "        ")
                    ifstmt.body.append(assign)
                    L += 1

                L += 1

            else:
                required.append(prop.attrname)

                assign = cls._makeAttrAssign("self", prop.attrname, prop.attrname, L, "    ")
                __init__body.append(assign)
                L += 1

                if isinstance(prop.cls, EBMLElement):
                    assign = cls._makeAttrAssign(f"_{prop.attrname}", "parent", "self", L, "    ")
                    __init__body.body.append(assign)
                    L += 1

        if not isinstance(cls.__dict__.get("ebmlID"), Constant):
            required.append("ebmlID")
            assign = cls._makeAttrAssign("self", "ebmlID", "ebmlID", L, "    ")
            __init__body.append(assign)
            L += 1

        assign = cls._makeAttrAssign("self", "readonly", "readonly", L, "    ")
        __init__body.append(assign)
        L += 1

        if L > 1:
            L += 1

        ifstmt = cls._makeIfNotNone("parent", L, "    ")
        __init__body.append(ifstmt)
        L += 1

        assign = cls._makeAttrAssign("self", "parent", "parent", L, "        ")
        ifstmt.body.append(assign)
        L += 2

        optional.extend(["readonly", "parent"])
        defaults.extend([False, None])
        __init__ = cls._makeFcnDef("__init__", required+optional, defaults, __init__body)

        mod = ast.Module(body=[__init__])
        module_code = compile(mod, 'Automatically-generated __init__', 'exec')

        func_code = [c for c in module_code.co_consts
            if isinstance(c, types.CodeType)][0]

        cls.__init__ = types.FunctionType(func_code, {},
            argdefs=tuple(defaults))

        if astor is not None:
            cls.__init__body__ = astor.to_source(__init__)

    def _prepare(cls):
        if "ebmlID" in cls.__dict__ and isinstance(cls.ebmlID, bytes):
            super().__setattr__("ebmlID", Constant(cls.ebmlID))

        __ebmlproperties__ = cls.__ebmlproperties__

        for prop in __ebmlproperties__:
            setattr(cls, prop.attrname, prop)

        if "__init__" not in cls.__dict__:
            cls._generate__init__()

class EBMLElement(object, metaclass=EBMLElementMetaClass):
    _parentEbmlID = None
    __ebmlproperties__ = (
            EBMLProperty("offsetInParent", int, optional=True),
            EBMLProperty("dataOffsetInParent", int, optional=True),
            EBMLProperty("dataSize", int, optional=True)
        )

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
        """
        Creates an deep copy of existing instance.
        """
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

        return False

    @readonly.setter
    def readonly(self, value):
        if self.readonly:
            raise AttributeError("Cannot change read-only status of read-only element. Use .copy() method.")
        self._readonly = bool(value)

    @property
    def parent(self):
        try:
            if isinstance(self._parent, weakref.ref):
                return self._parent()

            return self._parent

        except:
            return

    @parent.setter
    def parent(self, value):
        if self.readonly:
            raise AttributeError(f"Cannot set parent for read-only {type(self).__name__} element.")

        elif self._parentEbmlID is not None:
            if not isinstance(value, EBMLElement):
                raise ValueError(f"Parent of {type(self).__name__} element must be an EBMLElement.")

            if isinstance(self._parentEbmlID, bytes) and value.ebmlID != self._parentEbmlID:
                raise ValueError(f"Parent of {type(self).__name__} element must be an EBMLElement with EBML ID {self._parentEbmlID}.")

            elif isinstance(self._parentEbmlID, (tuple, list)) and value.ebmlID not in self._parentEbmlID:
                raise ValueError(f"Parent of {type(self).__name__} element must be an EBMLElement with EBML ID {self._parentEbmlID}.")

        try:
            self._parent = weakref.ref(value)

        except TypeError:
            self._parent = value

    @classmethod
    def makesubclass(cls, clsName, **attributes):
        return type(clsName, (cls,), attributes)

    def size(self):
        """Returns total size (in bytes) of element, including header and size element"""
        contentsize = self._size()

        if not isinstance(contentsize, int):
            raise TypeError(
                f"Invalid return value for {self.__class__.__name__}._size(). "
                f"Got '{type(contentsize).__name__}' instead.")

        return len(self.ebmlID) + len(ebml.util.toVint(contentsize)) + contentsize

    def _size(self):
        """To be implemented in subclasses"""
        raise NotImplementedError()

    def toFile(self, file):
        """
        Writes EBML data to file.
        """
        contentsize = self._size()
        file.write(self.ebmlID)
        file.write(ebml.util.toVint(contentsize))
        self._toFile(file)

    def _toFile(self, file):
        """Override if desired."""
        file.write(self._toBytes())

    def toBytes(self):
        """
        Returns the EBML data as a byte string.
        """
        contentsize = self._size()
        data = self._toBytes()

        if len(data) != contentsize:
            raise EncodeError(f"{self}: Length of data ({len(data)}) does not match advertised length ({contentsize}).")

        head = self.ebmlID + ebml.util.toVint(contentsize)

        if self.offsetInParent is not None and not self.readonly:
            self.dataOffsetInParent = self.offsetInParent + len(head)

        return head + data

    def _toBytes(self, file):
        """To be implemented in subclasses"""
        raise NotImplementedError()

    @classmethod
    def _readHead(cls, file):
        offset = file.tell()

        try:
            ebmlID = ebml.util.readVint(file)
            size = ebml.util.readVint(file)

            if cls.ebmlID is not None:
                if ebmlID != cls.ebmlID:
                    raise NoMatch

            return (offset, ebmlID, size)

        except NoMatch:
            raise

        except Exception as exc:
            raise DecodeError(
                f"Error reading EBML Element head at offset {offset}.",
                cls, offset, *sys.exc_info())

    @classmethod
    def fromFile(cls, file, parent=None):
        """
        Creates an instance using data from file.
        """
        (offset, ebmlID, size) = cls._readHead(file)

        try:
            size = ebml.util.fromVint(size)

            if cls.ebmlID is not None:
                return cls._fromFile(file, size, parent=parent)


            return cls._fromFile(file, size, ebmlID=ebmlID, parent=parent)

        except NoMatch:
            raise

        except Exception as exc:
            raise DecodeError(f"Error decoding EBML Element at offset {offset}.",
                                cls, offset, *sys.exc_info())

    @classmethod
    def _fromFile(cls, file, size, ebmlID=None, parent=None):
        """Override if desired."""
        data = file.read(size)

        if len(data) < size:
            raise UnexpectedEndOfData

        if ebmlID is not None:
            return cls._fromBytes(data, ebmlID=ebmlID, parent=parent)

        return cls._fromBytes(data, parent=parent)

    @classmethod
    def sniff(cls, file):
        """
        Without creating an instance, reads data from file. The default
        behavior of this function will be to return what will be the data
        attribute if an instance is created using fromFile(file).⎄
        """
        (offset, ebmlID, size) = cls._readHead(file)
        return cls._sniff(file, ebml.util.fromVint(size))

    @classmethod
    def _sniff(cls, file, size):
        return

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
        try:
            ebmlID, data = ebml.util.parseVint(data)
            size, data = ebml.util.parseVint(data)

            if cls.ebmlID is not None and cls.ebmlID != ebmlID:
                h = "".join([f"[{x:02x}]" for x in cls.ebmlID])
                g = "".join([f"[{x:02x}]" for x in ebmlID])
                raise NoMatch(f"Expected EBML ID {h}, got {g} instead.")

            if len(data) != ebml.util.fromVint(size):
                raise DecodeError(
                    f"Data length ({len(data)}) does not match encoded size "
                    f"({ebml.util.fromVint(size)}).")

            if cls.ebmlID is None:
                return cls._fromBytes(data, ebmlID=ebmlID, parent=parent)

            return cls._fromBytes(data, parent=parent)
        except Exception as exc:
            raise DecodeError(f"Error decoding EBML Element.",
                                cls, None, *sys.exc_info())

    @classmethod
    def _fromBytes(cls, data, ebmlID=None, parent=None):
        """To be implemented in subclasses"""
        raise NotImplementedError(
            f"Please implement {cls.__module__}.{cls.__name__}._fromBytes")

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

        if hasattr(self, "_repr_add") and callable(self._repr_add):
            params.append(self._repr_add())

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

    @staticmethod
    def _decodeData(data):
        return data

    @classmethod
    def _fromBytes(cls, data, ebmlID=None, parent=None):
        if ebmlID is not None:
            return cls(cls._decodeData(data),
                       ebmlID=ebmlID, parent=parent)

        return cls(cls._decodeData(data), parent=parent)

    @classmethod
    def _sniff(cls, file, size):
        data = file.read(size)
        return cls._decodeData(data)

class EBMLString(EBMLData):
    __ebmlproperties__ = (EBMLProperty("data", str),)
    encoding = "utf8"

    def _size(self):
        return len(self.data.encode(self.encoding))

    def _toBytes(self):
        return self.data.encode(self.encoding)

    @classmethod
    def _decodeData(cls, data):
        return data.decode(cls.encoding)


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

    @staticmethod
    def _decodeData(data):
        return int.from_bytes(data, byteorder="big")

    @classmethod
    def _sniff(cls, file, size):
        x = super()._sniff(file, size)
        return epoch + datetime.timedelta(microseconds=x/1000)


class Void(EBMLData):
    ebmlID = Constant(b"\xec")
    __ebmlproperties__ = (EBMLProperty("voidsize", int),)

    def _size(self):
        return self.voidsize

    @staticmethod
    def _decodeData(data):
        return len(data)

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
            # Attempt to seek past the data.
            file.seek(file.tell() + size)

        except io.UnsupportedOperation:
            file.read(size)

        return cls(size, parent=parent)

class EBMLInteger(EBMLData):
    data = EBMLProperty("data", int)
    signed = False
    __ebmlproperties__ = (data,)

    @data.sethook
    def data(self, value):
        try:
            value = int(value)

        except TypeError:
            print(value)
            raise TypeError(f"Cannot convert {value.__class__.__name__} object to integer for {self.__class__.__name__} element.")

        if value < 0 and not self.signed:
            raise ValueError("Signed integers not supported.")

        return value

    def _toBytes(self):
        k = self._size()
        return self.data.to_bytes(k, "big", signed=self.signed)

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
    def _decodeData(cls, data):
        return int.from_bytes(data, byteorder="big", signed=cls.signed)


class EBMLFloat(EBMLData):
    __ebmlproperties__ = (EBMLProperty("data", float),)

    def _toBytes(self):
        return struct.pack(">d", self.data)

    def _size(self):
        return 8

    @staticmethod
    def _decodeData(data):
        if len(data) == 4:
            return struct.unpack(">f", data)[0]

        elif len(data) == 8:
            return struct.unpack(">d", data)[0]

        raise DecodeError("Expected data size of either 4 or 8.")


class CRC32(EBMLData):
    ebmlID = b"\xbf"


def _addChildType(prop, cls, childTypes, __ebmlpropertiesbyid__):
    if isinstance(cls, (list, tuple)):
        for subcls in cls:
            _addChildType(prop, subcls, childTypes, __ebmlpropertiesbyid__)

    elif isinstance(cls, type) and issubclass(cls, EBMLElement):
        if cls.ebmlID is not None and cls.ebmlID not in childTypes:
            childTypes[cls.ebmlID] = cls
            __ebmlpropertiesbyid__[cls.ebmlID] = prop

        if cls is EBMLElement:
            if 0 in __ebmlpropertiesbyid__:
                raise ValueError(f"Can only specify one default property.")

            __ebmlpropertiesbyid__[0] = prop
            childTypes[0] = cls

    elif isinstance(cls, type) and issubclass(prop.cls, EBMLList):
        _addChildType(prop, cls.itemclass, childTypes, __ebmlpropertiesbyid__)

    else:
        raise TypeError("Expected EBMLElement subclass, EBMLList subclass, or list/tuple thereof. Got {cls} instead.")

class EBMLMasterElementMetaClass(EBMLElementMetaClass):
    def _prepare(cls):
        __ebmladdproperties__ = cls.__ebmladdproperties__
        __ebmlchildren__ = cls.__ebmlchildren__
        __ebmlpropertiesbyid__ = {}

        childTypes = {Void.ebmlID: Void, CRC32.ebmlID: CRC32}

        for prop in __ebmlchildren__:
            _addChildType(prop, prop.cls, childTypes, __ebmlpropertiesbyid__)

        if cls.allowunknown:
            ebmlchildren = EBMLList.makesubclass("EBMLChildList", tuple(childTypes.values()) + (EBMLData,))

        else:
            ebmlchildren = EBMLList.makesubclass("EBMLChildList", tuple(childTypes.values()))

        cls.__ebmlproperties__ = tuple(__ebmlchildren__) + tuple(__ebmladdproperties__) + (EBMLProperty("children", ebmlchildren, optional=True),)
        cls.__ebmlpropertiesbyid__ = __ebmlpropertiesbyid__
        
        if hasattr(cls, "_childTypes"):
            cls._childTypes.update(childTypes)
        else:
            cls._childTypes = childTypes

        super()._prepare()

class EBMLMasterElement(EBMLElement, metaclass=EBMLMasterElementMetaClass):
    __ebmlchildren__ = ()
    __ebmladdproperties__ = ()
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

    @classmethod
    def _getChildCls(cls, ebmlID):
        if cls.allowunknown:
            return cls._childTypes.get(ebmlID, EBMLData)

        else:
            return cls._childTypes.get(ebmlID)

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
            if not self.readonly and not child.readonly:
                child.offsetInParent = len(data)

            data += child.toBytes()

        return data

    def _decodeData(self, data):
        children = []

        for offset, ebmlID, sizesize, data in ebml.util.parseElements(data):
            childcls = self._getChildCls(ebmlID)

            if childcls is None:
                raise DecodeError(f"Unrecognized EBML ID {ebml.util.formatBytes(ebmlID)} while attempting to decode {self.__class__.__name__} Element.")

            child = childcls._fromBytes(data, parent=self)
            child.offsetInParent = offset
            child.dataOffsetInParent = offset + len(ebmlID) + sizesize
            child.dataSize = len(data)
            children.append(child)

            default = self.__ebmlpropertiesbyid__.get(0)
            prop = self.__ebmlpropertiesbyid__.get(ebmlID, default)

            if prop is not None:
                if isinstance(prop.cls, type) and issubclass(prop.cls, EBMLList):
                    if not hasattr(self, f"_{prop.attrname}"):
                        prop.__set__(self, [])

                    L = prop.__get__(self)
                    L.append(child)

                else:
                    if hasattr(self, f"_{prop.attrname}") and getattr(self, prop.attrname) is not None:
                        raise TypeError(f"Too many child elements of type '{prop.cls.__name__}' provided.")

                    prop.__set__(self, child)

            elif not isinstance(child, (Void, CRC32)) and not self.allowunknown:
                raise TypeError(f"Unexpected child type '{child.__class__.__name__}' for EBML Element '{self.__class__.__name__}'.")

            else:
                if not isinstance(child, (Void, CRC32)):
                    raise TypeError(f"Unexpected child type '{child.__class__.__name__}' for EBML Element '{self.__class__.__name__}'.")

        missing = []

        for prop in self.__ebmlchildren__:
            if not hasattr(self, f"_{prop.attrname}"):
                if not prop.optional:
                    missing.append(prop)
                else:
                    prop.__set__(self, None)

        l = [prop.cls.itemclass.__name__ if issubclass(prop.cls, EBMLList) else prop.cls.__name__ for prop in missing]

        if len(missing) == 1:
            raise DecodeError(f"Error decoding {self.__class__.__name__} element: Missing required element: {l[0]}.")
        elif len(missing) == 2:
            raise DecodeError(f"Error decoding {self.__class__.__name__} element: Missing required elements: {l[0]} and {l[1]}.")
        elif len(missing) > 2:
            raise DecodeError(f"Error decoding {self.__class__.__name__} element: Missing required elements: {', '.join(l[:-1])}, and {l[-1]}.")

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
