# Copyright 2026 The PEA knowledge processor authors
# SPDX-License-Identifier: Apache-2.0
"""A small JSON Schema checker (draft 2020-12, the part this project's schemas use) and a strict JSON reader.

Standard library only. The schemas in schema/ stay inside SUPPORTED; `unsupported_keywords` says so for a schema, and
the tests run it on every schema, so a keyword this checker would silently skip cannot slip in.
"""
import json
import math
import re

ANNOTATIONS = {"$schema", "$id", "title", "description", "examples", "$comment", "$defs"}
SUPPORTED = ANNOTATIONS | {
    "type", "properties", "required", "additionalProperties", "items", "enum", "const", "minLength", "maxLength",
    "pattern", "minimum", "maximum", "minItems", "maxItems", "uniqueItems", "$ref", "anyOf",
}


class NotJSON(ValueError):
    """The text is not the strict JSON this project accepts."""


def _no_constant(name):
    raise NotJSON("the number %s is not allowed" % name)


def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise NotJSON("the key %r is written twice" % key)
        out[key] = value
    return out


def _finite(text):
    value = float(text)
    if math.isinf(value) or math.isnan(value):
        raise NotJSON("a number too large to read")
    return value


def loads(data):
    """Strict JSON: UTF-8, no byte order mark, no NaN or Infinity, no number too large for a float, no key written
    twice in one object, not nested deeper than the parser allows. Raises NotJSON with the reason."""
    if isinstance(data, (bytes, bytearray)):
        try:
            data = bytes(data).decode("utf-8")
        except UnicodeDecodeError:
            raise NotJSON("not UTF-8 text") from None
    if data.startswith("﻿"):
        raise NotJSON("starts with a byte order mark")
    try:
        return json.loads(data, parse_constant=_no_constant, object_pairs_hook=_no_duplicates, parse_float=_finite)
    except NotJSON:
        raise
    except RecursionError:
        raise NotJSON("nested too deep") from None
    except ValueError as e:
        raise NotJSON("does not parse (%s)" % str(e)[:80]) from None


def dumps(value):
    """The one way this project writes JSON, so the same data always gives the same bytes: keys sorted, two spaces of
    indent, non-ASCII text written as it is, one line break at the end."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def unsupported_keywords(schema, path="#"):
    """Every keyword in `schema` that `validate` does not know, as "path: keyword"."""
    found = []
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key not in SUPPORTED:
                found.append("%s: %s" % (path, key))
            if key in ("properties", "$defs") and isinstance(value, dict):
                for name, sub in value.items():
                    found += unsupported_keywords(sub, "%s/%s/%s" % (path, key, name))
            elif key in ("items", "additionalProperties") and isinstance(value, dict):
                found += unsupported_keywords(value, "%s/%s" % (path, key))
            elif key == "anyOf":
                for i, sub in enumerate(value):
                    found += unsupported_keywords(sub, "%s/anyOf/%d" % (path, i))
    return found


def _is_type(value, name):
    if name == "null":
        return value is None
    if name == "boolean":
        return isinstance(value, bool)
    if name == "string":
        return isinstance(value, str)
    if name == "array":
        return isinstance(value, list)
    if name == "object":
        return isinstance(value, dict)
    if isinstance(value, bool):
        return False
    if name == "integer":
        return isinstance(value, int) or (isinstance(value, float) and value.is_integer())
    if name == "number":
        return isinstance(value, int) or (isinstance(value, float) and math.isfinite(value))
    raise ValueError("unknown type %r in a schema" % name)


def _resolve(ref, root):
    if not ref.startswith("#/"):
        raise ValueError("only references inside the same schema are supported: %r" % ref)
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def validate(value, schema, root=None, path="$", ignore_unknown=False):
    """Checks `value` against `schema`. Returns a list of (path, message); empty when the value conforms.

    ignore_unknown: members a schema does not name are skipped even where it says additionalProperties is false.
    A reader uses it for a file of a newer minor version (docs/FORMAT.md, "Versions").
    """
    root = schema if root is None else root
    errors = []
    if "$ref" in schema:
        errors += validate(value, _resolve(schema["$ref"], root), root, path, ignore_unknown)
    if "anyOf" in schema:
        if not any(not validate(value, sub, root, path, ignore_unknown) for sub in schema["anyOf"]):
            errors.append((path, "matches none of the allowed shapes"))
    if "const" in schema and not (value == schema["const"] and type(value) is type(schema["const"])):
        errors.append((path, "must be %r" % (schema["const"],)))
    if "enum" in schema and not any(value == e and type(value) is type(e) for e in schema["enum"]):
        errors.append((path, "is not one of the allowed values"))
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, n) for n in names):
            errors.append((path, "must be %s" % " or ".join(names)))
            return errors
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append((path, "is shorter than %d characters" % schema["minLength"]))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append((path, "is longer than %d characters" % schema["maxLength"]))
        elif "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append((path, "does not have the required form"))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append((path, "is below %s" % schema["minimum"]))
        if "maximum" in schema and value > schema["maximum"]:
            errors.append((path, "is above %s" % schema["maximum"]))
    elif isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append((path, "has fewer than %d entries" % schema["minItems"]))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append((path, "has more than %d entries" % schema["maxItems"]))
            return errors
        if schema.get("uniqueItems"):
            seen = set()
            for item in value:
                key = json.dumps(item, sort_keys=True)
                if key in seen:
                    errors.append((path, "has the same entry twice"))
                    break
                seen.add(key)
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                errors += validate(item, schema["items"], root, "%s[%d]" % (path, i), ignore_unknown)
    elif isinstance(value, dict):
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                errors.append((path, "lacks %r" % name))
        for name, item in value.items():
            if name in properties:
                errors += validate(item, properties[name], root, "%s.%s" % (path, name), ignore_unknown)
            elif schema.get("additionalProperties") is False:
                if not ignore_unknown:
                    errors.append((path, "has the unknown member %r" % name[:40]))
            elif isinstance(schema.get("additionalProperties"), dict):
                errors += validate(item, schema["additionalProperties"], root, "%s.%s" % (path, name), ignore_unknown)
    return errors
