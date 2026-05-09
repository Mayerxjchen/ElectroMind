from __future__ import annotations

import inspect
import json
from functools import reduce
from typing import Any, Union, get_args, get_origin, get_type_hints

from docstring_parser import parse


class FunctionTool:
    def __init__(self, name, description, parameters, func=None):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.func = func

    def to_dict(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def call(self, arguments=None):
        if self.func is None:
            raise ValueError(f"tool {self.name} has no bound function")

        if arguments is None:
            return str(self.func(**{}))

        if isinstance(arguments, str):
            stripped = arguments.strip()
            if not stripped:
                return str(self.func(**{}))
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as e:
                return f"Invalid JSON in tool arguments: {e}"
            return str(self.func(**payload))

        return str(self.func(**arguments))


def unwrap_optional(type_hint):
    origin = get_origin(type_hint)
    if origin is not Union:
        return False, type_hint

    args = get_args(type_hint)
    if type(None) not in args:
        return False, type_hint

    non_none_args = [arg for arg in args if arg is not type(None)]
    if len(non_none_args) == 1:
        return True, non_none_args[0]
    return True, reduce(lambda x, y: x | y, non_none_args)


def type_to_schema(type_hint):
    origin = get_origin(type_hint)
    if origin is list:
        args = get_args(type_hint)
        item_type = args[0] if args else Any
        return {"type": "array", "items": type_to_schema(item_type)}
    if origin is dict:
        return {"type": "object"}
    if type_hint is str:
        return {"type": "string"}
    if type_hint is int:
        return {"type": "integer"}
    if type_hint is float:
        return {"type": "number"}
    if type_hint is bool:
        return {"type": "boolean"}
    return {"type": "string"}


def extract_function_schema(func, name_override=None, description_override=None):
    func_name = name_override or func.__name__
    sig = inspect.signature(func)
    docstring = parse(func.__doc__ or "")
    description = description_override or docstring.short_description
    param_docs = {param.arg_name: param.description for param in docstring.params}
    type_hints = get_type_hints(func)

    properties = {}
    required = []
    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls", "context"):
            continue

        param_type = type_hints.get(param_name, Any)
        param_desc = param_docs.get(param_name)
        is_optional, base_type = unwrap_optional(param_type)
        schema = type_to_schema(base_type)
        if param_desc:
            schema["description"] = param_desc
        properties[param_name] = schema

        if param.default == inspect.Parameter.empty and not is_optional:
            required.append(param_name)

    json_schema = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
    return func_name, description, json_schema


def tool(name=None, description=None):
    def decorator(func):
        func_name, func_description, parameters = extract_function_schema(
            func,
            name_override=name,
            description_override=description,
        )
        return FunctionTool(
            name=func_name,
            description=func_description or "",
            parameters=parameters,
            func=func,
        )

    return decorator


def to_openai_tools(tools):
    return [ft.to_dict() for ft in tools]
