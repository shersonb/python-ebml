from ebml.base import EBMLInteger, EBMLString, EBMLMasterElement, EBMLProperty
#from ebml.util import TypeValidator, EBMLProperty

__all__ = ["EBMLVersion", "EBMLReadVersion", "EBMLMaxIDLength", "EBMLMaxSizeLength",
           "DocType", "DocTypeVersion", "DocTypeReadVersion", "EBMLHead"]

class EBMLVersion(EBMLInteger):
    ebmlID = b"\x42\x86"

class EBMLReadVersion(EBMLInteger):
    ebmlID = b"\x42\xf7"

class EBMLReadVersion(EBMLInteger):
    ebmlID = b"\x42\xf7"

class EBMLMaxIDLength(EBMLInteger):
    ebmlID = b"\x42\xf2"

class EBMLMaxSizeLength(EBMLInteger):
    ebmlID = b"\x42\xf3"

class DocType(EBMLString):
    ebmlID = b"\x42\x82"

class DocTypeVersion(EBMLInteger):
    ebmlID = b"\x42\x87"

class DocTypeReadVersion(EBMLInteger):
    ebmlID = b"\x42\x85"

class EBMLHead(EBMLMasterElement):
    ebmlID = b"\x1a\x45\xdf\xa3"
    __ebmlchildren__ = (
            EBMLProperty("ebmlVersion", EBMLVersion),
            EBMLProperty("ebmlReadVersion", EBMLReadVersion),
            EBMLProperty("ebmlMaxIDLength", EBMLMaxIDLength),
            EBMLProperty("ebmlMaxSizeLength", EBMLMaxSizeLength),
            EBMLProperty("docType", DocType),
            EBMLProperty("docTypeVersion", DocTypeVersion),
            EBMLProperty("docTypeReadVersion", DocTypeReadVersion)
        )
