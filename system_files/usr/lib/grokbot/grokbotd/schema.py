"""Load the API schema and validate call parameters against it.

Only the JSON Schema subset the API file uses is implemented (object
params with typed properties, enum, minimum/maximum,
minLength/maxLength, pattern and additionalProperties). Keeping it in the
standard library means the daemon needs nothing beyond python3.
"""
import json
import re

from . import paths

_TYPES = {
    "string": str, "boolean": bool, "integer": int, "number": (int, float),
    "object": dict, "array": list,
}


class ParamError(ValueError):
    pass


def load(path=None):
    with open(path or paths.schema_path(), encoding="utf-8") as f:
        doc = json.load(f)
    if not isinstance(doc.get("methods"), dict):
        raise ValueError("schema has no methods")
    return doc


def _check_type(value, typ):
    py = _TYPES.get(typ)
    if py is None:
        return True
    if typ in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, py)


def validate_params(spec, params):
    """Return params with defaults applied, or raise ParamError."""
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ParamError("params must be an object")
    pschema = spec.get("params", {})
    props = pschema.get("properties", {})
    if pschema.get("additionalProperties") is False:
        extra = sorted(set(params) - set(props))
        if extra:
            raise ParamError("unknown parameter(s): " + ", ".join(extra))
    out = dict(params)
    for name, p in props.items():
        if name in out:
            v = out[name]
            if not _check_type(v, p.get("type")):
                raise ParamError("%s must be %s" % (name, p.get("type")))
            if "enum" in p and v not in p["enum"]:
                raise ParamError("%s must be one of %s" % (name, ", ".join(map(str, p["enum"]))))
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                if "minimum" in p and v < p["minimum"]:
                    raise ParamError("%s must be >= %s" % (name, p["minimum"]))
                if "maximum" in p and v > p["maximum"]:
                    raise ParamError("%s must be <= %s" % (name, p["maximum"]))
            if isinstance(v, str):
                if len(v) < p.get("minLength", 0):
                    raise ParamError("%s is too short" % name)
                if "maxLength" in p and len(v) > p["maxLength"]:
                    raise ParamError("%s is too long" % name)
                if "pattern" in p and not re.search(p["pattern"], v):
                    raise ParamError("%s has an invalid format" % name)
        elif "default" in p:
            out[name] = p["default"]
    for name in pschema.get("required", []):
        if name not in out:
            raise ParamError("missing parameter: " + name)
    return out
