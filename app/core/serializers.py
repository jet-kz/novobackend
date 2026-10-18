from datetime import date, datetime
from uuid import UUID
from typing import Any, Optional

from sqlalchemy.inspection import inspect as sa_inspect


def to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(v) for v in value]
    return str(value)


def model_to_dict(instance: Any, extra: Optional[dict] = None) -> dict:
    if instance is None:
        return {}
    if isinstance(instance, dict):
        data = {k: to_jsonable(v) for k, v in instance.items()}
        if extra:
            data.update({k: to_jsonable(v) for k, v in extra.items()})
        return data
    data = {}
    mapper = sa_inspect(instance)
    for attr in mapper.mapper.column_attrs:
        data[attr.key] = to_jsonable(getattr(instance, attr.key))
    if extra:
        data.update({k: to_jsonable(v) for k, v in extra.items()})
    return data
