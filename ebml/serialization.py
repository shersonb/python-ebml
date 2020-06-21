#!/usr/bin/python3
from ebml.base import EBMLInteger, EBMLString, EBMLData, EBMLMasterElement, EBMLList, EBMLProperty, EBMLFloat, Constant, EBMLElement
from ebml.util import toVint, fromVint, parseVints, parseElements
import struct
import random
from fractions import Fraction as QQ
import importlib
import warnings
import types

class Bytes(EBMLData):
    ebmlID = b"\x81"

class String(EBMLString):
    ebmlID = b"\x82"

class Integer(EBMLInteger):
    ebmlID = b"\x84"
    signed = True

class Float(EBMLFloat):
    ebmlID = b"\x87"

class Rational(EBMLData):
    ebmlID = b"\x8a"
    __ebmlproperties__ = (EBMLProperty("data", QQ),)

    def _toBytes(self):
        for k in range(1, 9):
            if -2**(7*k - 1) <= self.data.numerator < 2**(7*k - 1) - 1:
                numdata = toVint(self.data.numerator + 2**(7*k - 1), k)
                break
        else:
            raise OverflowError

        dendata = toVint(self.data.denominator)
        return numdata+dendata

    def _size(self):
        for j in range(1, 9):
            if -2**(7*j - 1) <= self.data.numerator < 2**(7*j - 1) - 1:
                break
        else:
            raise OverflowError

        for k in range(1, 9):
            if -2**(7*k) <= self.data.denominator < 2**(7*k) - 1:
                break
        else:
            raise OverflowError

        return j + k

    @classmethod
    def _fromBytes(cls, data, parent=None):
        numdata, dendata = parseVints(data)
        return cls(QQ(fromVint(numdata) - 2**(7*len(numdata) - 1), fromVint(dendata)), parent=parent)

class Complex(EBMLData):
    ebmlID = b"\x8b"
    __ebmlproperties__ = (EBMLProperty("data", complex),)

    def _toBytes(self):
        return struct.pack(">dd", self.data.real, self.data.imag)

    def _size(self):
        return 16

    @classmethod
    def _fromBytes(cls, data, parent=None):
        if len(data) == 8:
            x, y = struct.unpack(">ff", data)

        elif len(data) == 16:
            x, y = struct.unpack(">dd", data)

        else:
            raise DecodeError("Expected data size of either 8 or 16.")

        return cls(x, parent=parent)

class Null(EBMLElement):
    ebmlID = b"\xfc"
    data = Constant(None)

    def _size(self):
        return 0

    def _toBytes(self):
        return b""

    @classmethod
    def _fromBytes(cls, data, parent=None):
        return cls()

class Bool(EBMLData):
    ebmlID = b"\xf2"
    __ebmlproperties__ = (EBMLProperty("data", bool),)

    def _size(self):
        return 1

    def _toBytes(self):
        return b"\x01" if self.data else b"\x00"

    @classmethod
    def _fromBytes(cls, data, parent=None):
        return cls(True) if len(data) and data[0] else cls(False)

class ObjID(EBMLInteger):
    ebmlID = b"\xf3"

class Ref(EBMLInteger):
    ebmlID = b"\xf4"

    def toObj(self, environ, refs):
        return refs[self.data]

class BaseObj(EBMLMasterElement):
    __ebmlchildren__ = (EBMLProperty("objID", ObjID, optional=True),)
    _typeMap = {
            str: String,
            bytes: Bytes,
            int: Integer,
            float: Float,
            QQ: Rational,
            complex: Complex,
            type(None): Null,
            bool: Bool
        }
    _typesByID = {cls.ebmlID: cls for cls in _typeMap.values()}
    _typesByID[Ref.ebmlID] = Ref

    @classmethod
    def _getChildCls(cls, ebmlID):
        childcls = cls._typesByID.get(ebmlID)

        if childcls:
            return childcls

        return super()._getChildCls(ebmlID)

    @classmethod
    def registerType(cls, subcls, ebmlcls):
        cls._typeMap[subcls] = ebmlcls
        cls._typesByID[ebmlcls.ebmlID] = ebmlcls

    @staticmethod
    def _createRef(refs):
        while True:
            n = random.randint(1, 2**32 - 1)

            if n not in refs:
                return n


    @classmethod
    def fromObj(cls, obj, environ=None, refs=None):
        """
        Create EBML Element from object.

        Specifying a dict object for 'environ' allows for creating/specifying environment variables that may
        affect creation of objects and their children. For example, one may wish to provide path information
        so that encoded path information may be interpreted relative to another path that is not stored
        anywhere in the EBML data structure.
        """
        if refs is None:
            refs = {}

        if environ is None:
            environ = {}

        if id(obj) in refs:
            return Ref(refs[id(obj)])

        elem = cls._fromObj(obj, environ, refs)

        if hasattr(elem, "objID") and elem.objID is not None:
            #print(id(obj), type(obj), obj)
            refs[id(obj)] = elem.objID

        return elem

    @classmethod
    def _wrapChild(cls, child, environ, refs):
        if id(child) in refs:
            return Ref(refs[id(child)])

        objcls = cls._typeMap.get(object)
        ebmlcls = cls._typeMap.get(type(child), objcls)

        if hasattr(ebmlcls, "fromObj"):
            return ebmlcls.fromObj(child, environ, refs)

        return ebmlcls(child)

    @classmethod
    def _fromObj(cls, obj, environ, refs):
        raise NotImplementedError(f"{cls.__name__}._fromObj not implemented.")

    def toObj(self, environ=None, refs=None):
        """
        Create object from EBML Element.

        Specifying a dict object for 'environ' allows for creating/specifying environment variables that may
        affect creation of EBML Elements and their children. For example, one may wish to store path
        information within an EBML data structure that is relative to another path that will not be stored
        anywhere in the EBML data structure.
        """
        if refs is None:
            refs = {}

        if environ is None:
            environ = {}

        obj = self._createObj(environ, refs)

        if self.objID:
            #print(self.objID, obj)
            refs[self.objID] = obj

        try:
            self._restoreState(obj, environ, refs)

        except NotImplementedError:
            pass

        try:
            self._restoreItems(obj, environ, refs)

        except NotImplementedError:
            pass

        try:
            self._restoreDict(obj, environ, refs)

        except NotImplementedError:
            pass

        return obj

    def _createObj(self, environ, refs):
        raise NotImplementedError(f"{self.__class__.__name__}._createObj not implemented.")

    def _restoreState(self, obj, environ, refs):
        raise NotImplementedError(f"{self.__class__.__name__}._restoreState not implemented.")

    def _restoreItems(self, obj, environ, refs):
        raise NotImplementedError(f"{self.__class__.__name__}._restoreItems not implemented.")

    def _restoreDict(self, obj, environ, refs):
        raise NotImplementedError(f"{self.__class__.__name__}._restoreDict not implemented.")

class Items(EBMLList):
    itemclass = EBMLElement

class Tuple(BaseObj):
    ebmlID = b"\xf6"
    __ebmlchildren__ = (
            EBMLProperty("objID", ObjID, optional=True),
            EBMLProperty("items", Items, optional=True)
        )

    @classmethod
    def _fromObj(cls, obj, environ, refs):
        return cls(items=[cls._wrapChild(child, environ, refs) for child in obj])

    def _createObj(self, environ, refs):
        if self.items:
            return tuple(item.toObj(environ, refs) if hasattr(item, "toObj") else item.data for item in self.items)

        return ()


class Args(Tuple):
    ebmlID = b"\xf8"

class List(BaseObj):
    ebmlID = b"\xf9"
    __ebmlchildren__ = (
            EBMLProperty("objID", ObjID, optional=True),
            EBMLProperty("items", Items, optional=True)
        )

    def __iter__(self):
        return iter(self.items)

    def __getitem__(self, index):
        return self.items[index]

    def __setitem__(self, index, value):
        self.items[index] = value

    def __len__(self):
        return len(self.items)

    def append(self, item):
        if self.items is None:
            self.items = []
            self.items.parent = self

        self.items.append(item)

    def extend(self, items):
        if self.items is None:
            self.items = []
            self.items.parent = self

        self.items.extend(items)

    def insert(self, index, item):
        if self.items is None:
            self.items = []
            self.items.parent = self

        self.items.insert(index, items)

    def _createObj(self, environ, refs):
        return []

    def _restoreItems(self, obj, environ, refs):
        if self.items:
            for item in self.items:
                if hasattr(item, "toObj"):
                    obj.append(item.toObj(environ, refs))

                else:
                    obj.append(item.data)

    @classmethod
    def _fromObj(cls, obj, environ, refs):
        ref = cls._createRef(refs)
        refs[id(obj)] = ref
        items = [cls._wrapChild(child, environ, refs) for child in obj]
        return cls(items=items, objID=ref)


class Pairs(EBMLList):
    itemclass = Tuple

class Dict(BaseObj):
    ebmlID = b"\x8d"
    __ebmlchildren__ = (
            EBMLProperty("objID", ObjID, optional=True),
            EBMLProperty("items", Pairs, optional=True)
        )

    def _createObj(self, environ, refs):
        return {}

    def _restoreDict(self, obj, environ, refs):
        if self.items:
            for item in self.items:
                key, val = item.toObj(environ, refs)
                obj[key] = val

    @classmethod
    def _fromObj(cls, obj, environ, refs):
        ref = cls._createRef(refs)
        #print(id(obj), type(obj), obj)
        refs[id(obj)] = ref
        return cls(items=[cls._wrapChild(child, environ, refs) for child in obj.items()], objID=ref)

    #def __init_subclass__(cls):
        #cls._typeMap = cls._typeMap.copy()

class Constructor(EBMLString):
    ebmlID = b"\xa9"

    @classmethod
    def fromObj(cls, constructor, environ=None, refs=None):
        if refs is None:
            refs = {}

        if environ is None:
            environ = {}

        module = environ.get("module")

        if isinstance(module, types.ModuleType):
            module = module.__name__

        if module is None:
            return cls(f"{constructor.__module__}.{constructor.__name__}")

        if constructor.__module__ == module:
            return cls(constructor.__name__)

        elif constructor.__module__.startswith(f"{module}."):
            return cls(f"{constructor.__module__[len(module) + 1:]}.{constructor.__name__}")

        raise ValueError(f"Function {constructor.__module__}.{constructor.__name__} is not a member of {module}.")

    def toObj(self, environ=None, refs=None):
        if refs is None:
            refs = {}

        if environ is None:
            environ = {}

        module = environ.get("module")

        if module is None:
            warnings.warn("Direct use of ebml.serialization.Object is insecure. Either subclass and override _createObj method, or specify module value in environ.", Warning)

            if "." in self.data:
                mod, fcn = self.data.rsplit(".", 1)

            else:
                mod, fcn = "__main__", self.data

            module = importlib.import_module(mod)
            return getattr(module, fcn)


        if isinstance(module, str):
            module = importlib.import_module(module)

        if "." in self.data:
            mod, fcn = self.data.rsplit(".", 1)

        else:
            mod, fcn = None, self.data

        if mod:
            submodule = importlib.import_module(f".{mod}", module.__name__)
            constructor = getattr(submodule, fcn)

        else:
            constructor = getattr(module, fcn)


        if constructor.__module__ != module.__name__ and not constructor.__module__.startswith(f"{module.__name__}."):
            raise ValueError(f"Function {constructor.__module__}.{constructor.__name__} not a member of {module.__name__}.")

        return constructor


class State(Tuple):
    ebmlID = b"\xac"

class StateDict(Dict):
    ebmlID = b"\xad"

    @classmethod
    def _fromObj(cls, obj, environ, refs):
        return cls(items=[cls._wrapChild(child, environ, refs) for child in obj.items()])

class Object(BaseObj):
    """
    Basis for EBML Elements serializing arbitrary objects through their __reduce__ methods.

    NOT secure. When subclassing, consider subclassing Args, State, StateDict, List, and Dict,
    and redefine __ebmlchildren__.
    """
    ebmlID = b"\xa8"

    __ebmlchildren__ = (
        EBMLProperty("objID", ObjID, optional=True),
        EBMLProperty("constructor", Constructor),
        EBMLProperty("args", Args),
        EBMLProperty("state", (State, StateDict), optional=True),
        EBMLProperty("items", List, optional=True),
        EBMLProperty("dict", Dict, optional=True),
        )

    # --- Methods related to converting EBML data structure to object ---

    def _getConstructor(self, environ):
        if hasattr(self, "_constructor") and isinstance(self._constructor, Constructor):
            return self._constructor.toObj(environ)

        elif hasattr(self, "constructor") and callable(self.constructor):
            return self.constructor

    def _constructArgs(self, environ, refs):
        return self.args.toObj(environ, refs)

    def _createObj(self, environ, refs):
        fcn = self._getConstructor(environ)
        args = self._constructArgs(environ, refs)
        return fcn(*args)

    def _restoreState(self, obj, environ, refs):
        if self.state:
            obj.__setstate__(self.state.toObj(environ, refs))

    def _restoreItems(self, obj, environ, refs):
        if self.items:
            for item in self.items:
                if hasattr(item, "toObj"):
                    obj.append(item.toObj(environ, refs))

                else:
                    obj.append(item.data)

    def _restoreDict(self, obj, environ, refs):
        if self.dict:
            for item in self.dict:
                key, val = item.toObj(environ, refs)
                obj[key] = val

    # --- Methods related to converting object to EBML data structure ---

    @classmethod
    def _fromObj(cls, obj, environ, refs={}):
        reduced = obj.__reduce__()

        ref = cls._createRef(refs)

        if len(reduced) == 2:
            constructor, args = reduced
            state = items = dictitems = None

        elif len(reduced) == 3:
            constructor, args, state = reduced
            items = dictitems = None

        elif len(reduced) == 4:
            constructor, args, state, items = reduced
            dictitems = None

        elif len(reduced) == 5:
            constructor, args, state, items, d = reduced

        self = cls._createElement(constructor, args, environ, refs)
        self.objID = refs[id(obj)] = ref

        if state:
            self._saveState(state, environ, refs)

        if items:
            self._saveItems(items, environ, refs)

        if dictitems:
            self._saveDict(dictitems, environ, refs)

        return self

    @classmethod
    def _createArgsElement(cls, args, environ, refs):
        return cls.args.cls.fromObj(args, environ, refs)

    @classmethod
    def _createConstructorElement(cls, constructor, environ, refs):
        return cls.constructor.cls.fromObj(constructor, environ, refs)

    @classmethod
    def _createElement(cls, constructor, args, environ, refs):
        constructor = cls._createConstructorElement(constructor, environ, refs)
        args = cls._createArgsElement(args, environ, refs)

        if constructor:
            if isinstance(args, tuple):
                return cls(constructor, *args)

            elif isinstance(args, dict):
                return cls(constructor, **args)

            elif isinstance(args, EBMLElement):
                return cls(constructor, args)

        else:
            if isinstance(args, tuple):
                return cls(*args)

            elif isinstance(args, dict):
                return cls(**args)

            elif isinstance(args, EBMLElement):
                return cls(args)

    def _saveState(self, state, environ, refs):
        if isinstance(state, dict):
            self.state = StateDict.fromObj(state, environ, refs)

        if isinstance(state, (tuple, list)):
            self.state = State.fromObj(state, environ, refs)

    def _saveItems(self, items, environ, refs):
        self.items = self.__class__.items.cls()

        for item in items:
            self.items.append(self._wrapChild(item, environ, refs))

    def _saveDict(self, d, refs):
        self.dict.items = self.__class__.dict.cls()

        for item in d.items():
            self.dict.items.append(self._wrapChild(item, environ, refs))

BaseObj.registerType(tuple, Tuple)
BaseObj.registerType(list, List)
BaseObj.registerType(dict, Dict)
BaseObj.registerType(object, Object)

