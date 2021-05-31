class NoMatch(Exception):
    pass

class DecodeError(Exception):
    def __init__(self, message, elementcls, offset=None, excclass=None, exc=None, tb=None):
        self.elementcls = elementcls
        self.offset = offset
        self.excclass = excclass
        self.exc = exc
        self.tb = tb
        if elementcls:
            super().__init__(f"{message} [{elementcls.__name__}]")

        else:
            super().__init__(message)

class EncodeError(Exception):
    pass

class UnexpectedEndOfData(Exception):
    pass

class WriteError(Exception):
    pass

class ReadError(Exception):
    pass

class ResizeError(Exception):
    pass
