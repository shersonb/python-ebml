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

#class constant(property):
    #"""
    #Constant attribute.
    #"""
    #def __init__(self, value):

        #if isinstance(value, bytes):
            #k = len(value)

            #if value[0] & (1 << (8 - k)) and (value[0] != 2**(8 - k) - 1 or value[1:] != b"\xff"*(k - 1)):
                #self._ebmlID = value
            #else:
                #raise ValueError(f"Not a valid EBML ID: {formatBytes(value)}.")

        #elif isinstance(value, int) and value >= 0:
            #ebmlID = ebml.util.toVint(value)

            #if isinstance(ebmlID, bytes):
                #self._ebmlID = ebmlID
                #return
            #else:
                #raise ValueError(f"Integer value too big.")

        #else:
            #raise AttributeError("Expecting bytes or int object.")

        #property.__init__(self, fget=self._fget)

    #def _fget(self, inst):
        #return self._ebmlID

#class ebmlproperty(property):
    #"""
    #Attribute type enforcement.
    
    #Usage:
    #>>> a = Custom()
    #>>> a.x = 1
    #>>> a.x = 1 ; a.x
    #1
    #>>> a.x = 2.0 ; a.x
    #2
    #>>> a.y = 3 ; a.y
    #3.0
    #>>> del a.x
    #Traceback (most recent call last):
    #File "<stdin>", line 1, in <module>
    #AttributeError: can't delete attribute
    #>>> del a.y
    #>>> a.y
    #"""
    #def __init__(self, propname, cls, attrname=None, optional=False, setterhook=None):
        #self.propname = propname
        #self.attrname = attrname
        #self.cls = cls
        #self.optional = optional
        #self._setterhook = setterhook
        #if optional:
            #property.__init__(self, fget=self._fget, fset=self._fset2, fdel=self._fdel)
        #else:
            #property.__init__(self, fget=self._fget, fset=self._fset)

    #def setterhook(self, func):
        #self._setterhook = func
        #return self

    #def _fget(self, inst):
        #if inst is None:
            #return self

        #try:
            #obj = getattr(inst, f"_{self.propname}")

        #except AttributeError:
            #if self.optional:
                #return

            #raise

        #if obj is not None and self.attrname is not None:
            #return getattr(obj, self.attrname)

        #return obj

    #def _fset(self, inst, value):
        #if callable(self._setterhook):
            #value = self._setterhook(inst, value)

        #if inst.readonly:
            #raise AttributeError("Cannot change attribute for read-only element.")

        #if isinstance(value, self.cls):
            #setattr(inst, f"_{self.propname}", value)

        #elif hasattr(inst, f"_{self.propname}"):
            #obj = getattr(inst, f"_{self.propname}")

            #if isinstance(obj, self.cls) and self.attrname:
                #setattr(obj, self.attrname, value)

            #else:
                #if isinstance(self.cls, tuple):
                    #raise TypeError("Multiple classes specified. Cowardly refusing to automatically instantiate class.")
                #setattr(inst, f"_{self.propname}", self.cls(value))
        #else:

            #if isinstance(self.cls, tuple):
                #raise TypeError("Multiple classes specified. Cowardly refusing to automatically instantiate class.")

            #setattr(inst, f"_{self.propname}", self.cls(value))

    #def _fset2(self, inst, value):
        #if callable(self._setterhook):
            #value = self._setterhook(inst, value)

        #if inst.readonly:
            #raise AttributeError("Cannot change attribute for read-only element.")

        #if value is None:
            #setattr(inst, f"_{self.propname}", value)

        #else:
            #self._fset(inst, value)

    #def _fdel(self, inst):
        #setattr(inst, f"_{self.propname}", None)

#class TypeValidator(object):
    #def __init__(self, attrname, cls, optional=False, sethook=None, clskwargs={}):
        #self.attrname = attrname
        #self._attrname = f"_{attrname}"

        #self.cls = cls
        #self.optional = optional

        #self._sethook = sethook
        #self.clskwargs = clskwargs.copy()

    #@property
    #def propname(self):
        #return self.attrname

    #def sethook(self, func):
        #self._sethook = func
        #return self

    #def __get__(self, inst, cls=None):
        #if inst is None:
            #return self

        #try:
            #obj = getattr(inst, self._attrname)

        #except AttributeError:
            #if self.optional:
                #return

            #raise

        #return obj

    #def __set__(self, inst, value):
        #if value is None:
            #return self.__delete__(inst)

        #if hasattr(inst, "readonly") and inst.readonly:
            #raise AttributeError("Cannot change attribute for read-only element.")

        #if callable(self._sethook):
            #value = self._sethook(inst, value)

        #if not isinstance(value, self.cls):
            #if isinstance(self.cls, tuple):
                #raise TypeError("Multiple classes specified. Cowardly refusing to automatically instantiate class.")

            #value = self.cls(value)

        #setattr(inst, self._attrname, value)

    #def __delete__(self, inst):
        #if hasattr(inst, "readonly") and inst.readonly:
            #raise AttributeError("Cannot change attribute for read-only element.")

        #if not self.optional:
            #raise AttributeError("Cannot delete required attribute.")

        #setattr(inst, self._attrname, None)

#class FilePointer(object):
    #pass

#class EBMLValidator(TypeValidator):
    #def __init__(self, attrname, cls, optional=False, sethook=None, clskwargs={}, allowpointer=False):
        #super().__init__(attrname, cls, optional, sethook, clskwargs)
        #self.allowpointer = allowpointer

    #def __get__(self, inst, cls=None):
        ##if inst is None:
            ##return self

        #obj = super().__get__(inst, cls)

        #if isinstance(obj, FilePointer):
            #origoffset = obj.body.tell()
            #obj = self.cls.fromFile(obj.file, readonly=True, parent=inst)
            #obj.body.seek(origoffset)

        #try:
            #return obj.data
        #except AttributeError:
            #return obj

    #def __set__(self, inst, value):
        ##import time
        ##t0 = time.time()
        #if value is None:
            #return self.__delete__(inst)

        #if hasattr(inst, "readonly") and inst.readonly:
            #raise AttributeError("Cannot change attribute for read-only element.")

        #if callable(self._sethook):
            #value = self._sethook(inst, value)

        #if isinstance(value, self.cls):
            ##t1 = time.time()
            #setattr(inst, self._attrname, value)
            ##t2 = time.time()
            ##print(f"EBMLValidator.__set__ (case self.cls) {t2 - t1:.8f} {t1 - t0:.8f} {t2 - t0:.8f}")
            #return

        #elif isinstance(value, FilePointer):
            #if not self.allowpointer:
                #raise ValueError("FilePointer not permitted here.")
            ##t1 = time.time()
            #setattr(inst, self._attrname, value)
            ##t2 = time.time()
            ##print(f"EBMLValidator.__set__ (case FilePointer) {t2 - t1:.8f} {t1 - t0:.8f} {t2 - t0:.8f}")
            #return

        #try:
            #obj = super().__get__(inst)
        #except AttributeError:
            #obj = None

        ##t1 = time.time()
        #if obj is None and hasattr(self.cls, "data"):
            #if isinstance(self.cls, tuple):
                #raise TypeError("Multiple classes specified. Cowardly refusing to automatically instantiate class.")

            #obj = self.cls(data=value, parent=inst, **self.clskwargs)
            ##t2 = time.time()

            #setattr(inst, self._attrname, obj)
            ##t3 = time.time()

            ##print(f"EBMLValidator.__set__ (instance created) {t3 - t2:.8f} {t2 - t1:.8f} {t1 - t0:.8f} {t3 - t0:.8f}")

        #elif hasattr(obj, "data"):
            #obj.data = value
            ##t2 = time.time()
            ##print(f"EBMLValidator.__set__ (with data attribute) {t2 - t1:.8f} {t1 - t0:.8f} {t2 - t0:.8f}")

        #else:
            #raise AttributeError("Unable to set attribute.")

    #def _fset2(self, inst, value):
        #if callable(self._setterhook):
            #value = self._setterhook(inst, value)

        #if inst.readonly:
            #raise AttributeError("Cannot change attribute for read-only element.")

        #if value is None:
            #setattr(inst, f"_{self.propname}", value)

        #else:
            #self._fset(inst, value)

    #def _fdel(self, inst):
        #setattr(inst, f"_{self.propname}", None)

#class EBMLList(list):
    #"""Item type enforcement."""

    #itemclass = object
    #clskwargs = {}

    #def __init__(self, items=[], parent=None):
        #self.parent = parent
        #list.__init__(self, [item if isinstance(item, self.itemclass) else self.itemclass(item, parent=parent, **self.clskwargs) for item in items])

        #for item in self:
            #if hasattr(item, "parent"):
                #item.parent = self.parent

    #def copy(self, parent=None):
        #cls = type(self)

        #if hasattr(self.itemclass, "copy") and callable(self.itemclass.copy):
            ##t1 = time.time()
            #new = cls([item.copy() for item in list.__iter__(self)], parent=parent)
            ##t2 = time.time()
            ##print(t2 - t1, t1 - t0, t2 - t0)
            #return new

        #return cls(list.__iter__(self), parent=parent)

    ##def copy(self, parent=None):
        ##cls = type(self)
        ##new = []
        ##for item in self:
            ##if hasattr(item, "copy") and callable(item.copy):
                ##new.append(item.copy())
            ##else:
                ##new.append(item)

        ##return cls(new, parent=parent)

    #def extend(self, items):
        #k = len(self)
        #list.extend(self, [item if isinstance(item, self.itemclass) else self.itemclass(item, parent=self.parent, **self.clskwargs) for item in items])
        #for item in self[k:]:
            #if hasattr(item, "parent"):
                #item.parent = self.parent

    #def append(self, item):
        ##print(f"{self.itemclass}, {item}, {self.parent}")
        #if not isinstance(item, self.itemclass):
            #if isinstance(self.itemclass, tuple):
                #raise TypeError("Multiple item classes specified. Cowardly refusing to automatically instantiate class.")
            #item = self.itemclass(item, parent=self.parent, **self.clskwargs)
        #if hasattr(item, "parent"):
            #item.parent = self.parent
        #list.append(self, item)

    #def insert(self, index, item):
        #if not isinstance(item, self.itemclass):
            #if isinstance(self.itemclass, tuple):
                #raise TypeError("Multiple item classes specified. Cowardly refusing to automatically instantiate class.")
            #item = self.itemclass(item, parent=self.parent, **self.clskwargs)
        #if hasattr(item, "parent"):
            #item.parent = self.parent
        #list.insert(self, index, item)

    #def __getitem__(self, index):
        #item = list.__getitem__(self, index)
        #try:
            #return item.data
        #except AttributeError:
            #return item

    #def pop(self, index):
        #item = list.pop(self, index)
        #try:
            #return item.data
        #except AttributeError:
            #return item

    #def __setitem__(self, index, item):
        #if isinstance(item, self.itemclass):
            #if hasattr(item, "parent"):
                #item.parent = self.parent

            #return list.__setitem__(self, index, item)

        #try:
            #obj = list.__getitem__(self, index)
        #except IndexError:
            #raise IndexError("list assignment index out of range")

        #if hasattr(obj, "data"):
            #obj.data = item
        #else:
            #raise AttributeError("Cannot set data attribute.")

    #@classmethod
    #def makesubclass(cls, name, itemclass, attrname=None):
        #return type(name, (cls,), {"itemclass": itemclass, "attrname": attrname})

    #@property
    #def parent(self):
        #return self._parent

    #@parent.setter
    #def parent(self, value):
        #self._parent = value
        #for item in self:
            #item.parent = value

#def makeinit(args, optional=()):
    #init_body = []
    #func_body = []
    #n = len(args)
    #offset = len("def __init__(")
    #astarg = ast.arg(arg="self", lineno=1, col_offset=offset)
    #func_args = [astarg]
    #offset += len("self, ")

    #defaults = []
    #argdefs = []
    #N = 5

    #for k, arg in enumerate(tuple(args) + tuple(optional)):
        #astarg = ast.arg(arg=arg, lineno=1, col_offset=offset)
        #if k < n:
            #offset += len(arg) + 2
        #else:
            #offset += len(arg) + 1
            #defaults.append(ast.NameConstant(value=None, lineno=1, col_offset=offset))
            #argdefs.append(None)
            #offset += 2

        #func_args.append(astarg)

        ##self = ast.Name(id="self", lineno=k + 2, col_offset=4, ctx=ast.Load())
        ##target = ast.Attribute(attr=arg, value=self, lineno=k + 2, col_offset = 4, ctx=ast.Store())
        ##value = ast.Name(id=arg, lineno=k + 2, col_offset=len(f"    self.{arg} = "), ctx=ast.Load())
        ##func_body.append(ast.Assign(targets=[target], value=value, lineno=k + 2, col_offset=4))

        #"""
        #self.attr = attr
        #try:
            #attr.parent = self
        #except AttributeError:
            #pass
        #"""

        #self = ast.Name(id="self", lineno=N*k + 2, col_offset=4, ctx=ast.Load())
        #target = ast.Attribute(attr=arg, value=self, lineno=N*k + 2, col_offset = len(f"    self."), ctx=ast.Store())
        #value = ast.Name(id=arg, lineno=N*k + 2, col_offset=len(f"    self.{arg} = "), ctx=ast.Load())
        #func_body.append(ast.Assign(targets=[target], value=value, lineno=N*k + 2, col_offset=len(f"    self.{arg} ")))

        #if arg is not "parent":
            #self = ast.Name(id="self", lineno=N*k + 2, col_offset=4, ctx=ast.Load())
            #attribute = ast.Attribute(attr=f"_{arg}", value=self, lineno=N*k + 2, col_offset = len(f"    self."), ctx=ast.Load())
            #target = ast.Attribute(attr="parent", value=attribute, lineno=N*k + 4, col_offset=len(f"        self._{arg}."), ctx=ast.Store())
            #value = ast.Name(id="self", lineno=N*k + 4, col_offset=len(f"        self._{arg}.parent = "), ctx=ast.Load())
            #assign = ast.Assign(targets=[target], value=value, lineno=N*k + 4, col_offset=len(f"        self._{arg}.parent "))

            #pass_ = ast.Pass(lineno=N*k + 6, col_offset=8)
            #attrerror = ast.Name(id="AttributeError", lineno=N*k + 5, col_offset=len(f"    except "), ctx=ast.Load())
            #handler = ast.ExceptHandler(attrerror, None, [pass_], lineno=N*k + 4, col_offset=4)

            #try_ = ast.Try([assign], [handler], [], [], lineno=N*k + 3, col_offset=4)

            #func_body.append(try_)

    #astargs = ast.arguments(args=func_args, defaults=defaults, kwonlyargs=[], kw_defaults=[])
    #func = ast.FunctionDef(name="__init__", args=astargs, body=func_body,
                       #decorator_list=[],
                       #returns=None, lineno=1, col_offset=0)

    #fcnsrc = "\n".join(tosrc(func))

    #mod = ast.Module(body=[func])
    ##print(ast.dump(func))
    #module_code = compile(mod, '<generated-ast>', 'exec')
    #func_code = [c for c in module_code.co_consts
        #if isinstance(c, types.CodeType)][0]

    #fcn = types.FunctionType(func_code, {"AttributeError": AttributeError},
        #argdefs=tuple(argdefs))
    #fcn.__source__ = fcnsrc
    #return fcn

#def tosrc(astobj, indent=""):
    #if isinstance(astobj, list):
        #lines = []

        #for line in astobj:
            #src = tosrc(line)

            #if isinstance(src, list):
                #if len(lines):
                    #lines.append("")

                #lines.extend([f"{indent}{item}" if len(item) else "" for item in src])
            #elif len(src):
                #lines.append(f"{indent}{src}")
            #else:
                #lines.append("")
        #return lines

    #elif isinstance(astobj, ast.Expr):
        #return tosrc(astobj.value)

    #elif isinstance(astobj, ast.Module):
        #return tosrc(astobj.body)

    #elif isinstance(astobj, ast.Name):
        #return f"{indent}{astobj.id}"

    #elif isinstance(astobj, ast.NameConstant):
        #return f"{indent}{astobj.value}"

    #elif isinstance(astobj, ast.Num):
        #return f"{indent}{astobj.n}"

    #elif isinstance(astobj, ast.Add):
        #return f" + "

    #elif isinstance(astobj, ast.Sub):
        #return f" - "

    #elif isinstance(astobj, ast.Mult):
        #return f"*"

    #elif isinstance(astobj, ast.Pass):
        #return f"{indent}pass"

    #elif isinstance(astobj, ast.Attribute):
        #return f"{indent}{tosrc(astobj.value)}.{astobj.attr}"

    #elif isinstance(astobj, ast.arg):
        #return f"{indent}{astobj.arg}"

    #elif isinstance(astobj, ast.arguments):
        #if len(astobj.defaults):
            #k = len(astobj.defaults)
            #return ", ".join([f"{tosrc(arg)}" for arg in astobj.args[:-k]] + [f"{tosrc(arg)}={tosrc(default)}" for arg, default in zip(astobj.args[-k:], astobj.defaults)])
        #else:
            #return ", ".join([f"{tosrc(arg)}" for arg in astobj.args])

    #elif isinstance(astobj, ast.FunctionDef):
        #lines = [f"def {astobj.name}({tosrc(astobj.args)}):"]
        #lines.extend(tosrc(astobj.body, indent="    "))
        #lines.append("")
        #return [indent+line if len(line) else "" for line in lines]

    #elif isinstance(astobj, ast.If):
        #lines = [f"if {tosrc(astobj.test)}:"]
        #lines.extend(tosrc(astobj.body, indent="    "))
        #lines.append("")

        #print(astobj.orelse)

        #while astobj.orelse is not None and len(astobj.orelse) == 1 and isinstance(astobj.orelse[0], ast.If):
            #astobj = astobj.orelse[0]
            #lines.append(f"elif {tosrc(astobj.test)}:")
            #lines.extend(tosrc(astobj.body, indent="    "))
            #lines.append("")

        #if astobj.orelse is not None and len(astobj.orelse):
            #lines.append(f"else:")
            #lines.extend(tosrc(astobj.orelse, indent="    "))
            #lines.append("")

        #return lines

    #elif isinstance(astobj, ast.Try):
        #lines = ["try:"]
        #lines.extend(tosrc(astobj.body, indent="    "))
        #lines.append("")

        #if len(astobj.handlers):
            #for handler in astobj.handlers:
                #lines.extend(tosrc(handler))

        #return [indent+line if len(line) else "" for line in lines]

    #elif isinstance(astobj, ast.ExceptHandler):
        #lines = []
        #if astobj.type and astobj.name:
            #lines.append(f"except {tosrc(astobj.type)} as {tosrc(astobj.name)}:")
        #elif astobj.type:
            #lines.append(f"except {tosrc(astobj.type)}:")
        #lines.extend(tosrc(astobj.body, indent="    "))
        #lines.append("")
        #return [indent+line if len(line) else "" for line in lines]

    #elif isinstance(astobj, ast.Assign):
        #if len(astobj.targets) == 1:
            #return f"{indent}{tosrc(astobj.targets[0])} = {tosrc(astobj.value)}"

    #elif isinstance(astobj, ast.BinOp):
        #orderofops = {ast.Add: 0, ast.Sub: 0, ast.Mult: 1, ast.Div: 1, ast.Pow: 2}

        #if isinstance(astobj.left, ast.BinOp) and orderofops[type(astobj.left.op)] < orderofops[type(astobj.op)]:
            #left = f"({tosrc(astobj.left)})"
        #else:
            #left = tosrc(astobj.left)

        #if isinstance(astobj.right, ast.BinOp) and orderofops[type(astobj.right.op)] < orderofops[type(astobj.op)]:
            #right = f"({tosrc(astobj.right)})"
        #else:
            #right = tosrc(astobj.right)
        #return f"{indent}{left}{tosrc(astobj.op)}{right}"

    #else:
        #raise TypeError(f"Do not know how to handle {type(astobj).__name__}")

