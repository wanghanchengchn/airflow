from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Iterable as _Iterable, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class task_invoke(_message.Message):
    __slots__ = ["args"]
    ARGS_FIELD_NUMBER: _ClassVar[int]
    args: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, args: _Optional[_Iterable[str]] = ...) -> None: ...

class task_reply(_message.Message):
    __slots__ = ["timing"]
    TIMING_FIELD_NUMBER: _ClassVar[int]
    timing: bytes
    def __init__(self, timing: _Optional[bytes] = ...) -> None: ...
