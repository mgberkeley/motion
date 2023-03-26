from datetime import date, datetime
from abc import ABC
from collections import namedtuple
from enum import Enum
import pyarrow as pa

# import pyarrow.extension as pa_ext
from pydantic import BaseModel, Extra

import inspect
import numpy as np
import pickle
import typing


class MEnum(Enum):
    @classmethod
    def list(cls):
        return [e.value for e in cls]


Field = namedtuple("Field", ["name", "type_"])


def type_to_name(t):
    return t.__name__.split(".")[-1].upper()


TYPE_TO_PA_TYPE = {
    int: pa.int64(),
    str: pa.string(),
    float: pa.float64(),
    bool: pa.bool_(),
    date: pa.date32(),
    datetime: pa.timestamp("us"),
    bytes: pa.binary(),
}


def get_arrow_type(t):
    if t in TYPE_TO_PA_TYPE.keys():
        return TYPE_TO_PA_TYPE[t]

    elif inspect.isclass(t) and issubclass(t, MEnum):
        # return pa_ext.EnumType.from_enum(t)
        return pa.string()

    elif typing.get_origin(t) == list:
        sub_t = typing.get_args(t)[0]
        return pa.list_(get_arrow_type(sub_t))

    elif typing.get_origin(t) == dict:
        kt = typing.get_args(t)[0]
        vt = typing.get_args(t)[1]
        return pa.map_(get_arrow_type(kt), get_arrow_type(vt))

    # Check if numpy type
    elif issubclass(t, np.generic) or issubclass(t, np.ndarray):
        return pa.from_numpy_dtype(t)

    # TODO: Add support for other types
    raise TypeError(f"Type {t} not supported.")


class Schema(BaseModel, extra=Extra.allow):
    identifier: str
    derived_id: str
    create_at: datetime
    session_id: str

    @classmethod
    def formatPaSchema(cls, relation: str) -> pa.Schema:
        """Formats a pyarrow schema for the given relation.

        Args:
            table_name (str): Name of relation.

        Returns:
            pa.Schema: Schema for table based on annotations.
        """

        fields = [Field(key, val) for key, val in cls.__annotations__.items()]
        user_defined_fields = [
            f
            for f in fields
            if not f.name == "identifier"
            and not f.name == "create_at"
            and not f.name == "derived_id"
            and not f.name == "session_id"
        ]
        pa_fields = [
            pa.field("identifier", pa.string(), nullable=False),
            pa.field(
                "create_at",
                pa.timestamp("us"),
                nullable=False,
            ),
            pa.field("derived_id", pa.string()),
            pa.field("session_id", pa.string(), nullable=False),
        ]

        for field in user_defined_fields:
            try:
                arrow_type = get_arrow_type(field.type_)
            except TypeError as e:
                raise TypeError(f"Error in {relation}.{field.name}: {e}")
            pa_fields.append(pa.field(field.name, arrow_type))

        schema = pa.schema(pa_fields)
        return schema
