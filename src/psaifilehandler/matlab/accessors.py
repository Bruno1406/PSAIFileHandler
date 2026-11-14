from __future__ import annotations

import ast
from collections.abc import Mapping
from typing import Any


class PathAccessor:
    """Safely compiles and evaluates declarative accessor paths against MATLAB struct objects."""

    def __init__(self, expr: str) -> None:
        if not isinstance(expr, str) or not expr.strip():
            raise ValueError(f"Path expression must be a non-empty string, got {expr!r}")
        self.expr = expr.strip()
        try:
            self._tree = ast.parse(self.expr, mode="eval")
        except SyntaxError as e:
            raise ValueError(f"Syntax error in accessor expression '{self.expr}': {e}") from e

    def __call__(self, root_obj: Any) -> Any:
        return self._eval_node(self._tree.body, root_obj)

    def _eval_node(self, node: ast.AST, root_obj: Any) -> Any:
        if isinstance(node, ast.Expression):
            return self._eval_node(node.body, root_obj)

        if isinstance(node, ast.Name):
            if node.id in ("elem", "exp", "x", "root"):
                return root_obj
            if isinstance(root_obj, Mapping) and node.id in root_obj:
                return root_obj[node.id]
            if hasattr(root_obj, node.id):
                return getattr(root_obj, node.id)
            if hasattr(root_obj, "__getitem__"):
                try:
                    return root_obj[node.id]
                except Exception:
                    pass
            avail = list(root_obj.keys()) if hasattr(root_obj, "keys") else [a for a in dir(root_obj) if not a.startswith("_")]
            raise AttributeError(f"Root object has no field '{node.id}'. Available fields: {avail}")

        if isinstance(node, ast.Attribute):
            val = self._eval_node(node.value, root_obj)
            attr = node.attr
            if hasattr(val, attr):
                return getattr(val, attr)
            if isinstance(val, Mapping) and attr in val:
                return val[attr]
            if hasattr(val, "__getitem__"):
                try:
                    return val[attr]
                except Exception:
                    pass
            sub_expr = ast.unparse(node.value)
            raise AttributeError(f"Failed to resolve attribute '{attr}' on sub-expression '{sub_expr}' (type: {type(val).__name__})")

        if isinstance(node, ast.Subscript):
            val = self._eval_node(node.value, root_obj)
            idx = self._eval_node(node.slice, root_obj)
            try:
                return val[idx]
            except Exception as e:
                sub_expr = ast.unparse(node)
                raise KeyError(f"Subscript evaluation failed at sub-expression '{sub_expr}': {e}") from e

        if isinstance(node, ast.Call):
            func = self._eval_node(node.func, root_obj)
            args = [self._eval_node(a, root_obj) for a in node.args]
            kwargs = {kw.arg: self._eval_node(kw.value, root_obj) for kw in node.keywords}
            try:
                return func(*args, **kwargs)
            except Exception as e:
                sub_expr = ast.unparse(node)
                raise RuntimeError(f"Call evaluation failed at sub-expression '{sub_expr}': {e}") from e

        if isinstance(node, ast.Constant):
            return node.value

        if isinstance(node, ast.Tuple):
            return tuple(self._eval_node(elt, root_obj) for elt in node.elts)

        if isinstance(node, ast.List):
            return [self._eval_node(elt, root_obj) for elt in node.elts]

        if isinstance(node, ast.Slice):
            lower = self._eval_node(node.lower, root_obj) if node.lower is not None else None
            upper = self._eval_node(node.upper, root_obj) if node.upper is not None else None
            step = self._eval_node(node.step, root_obj) if node.step is not None else None
            return slice(lower, upper, step)

        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return -self._eval_node(node.operand, root_obj)
            if isinstance(node.op, ast.UAdd):
                return +self._eval_node(node.operand, root_obj)
            raise TypeError(f"Unsupported unary operator: {type(node.op).__name__}")

        raise TypeError(f"Unsupported AST node '{type(node).__name__}' in path expression '{self.expr}'")

    def __repr__(self) -> str:
        return f"PathAccessor('{self.expr}')"


def compile_accessor(val: Any) -> Any:
    """Compile accessor into a PathAccessor if string, or return as is."""
    if val is None or isinstance(val, PathAccessor) or callable(val):
        return val
    if isinstance(val, str):
        return PathAccessor(val)
    return val


def evaluate_accessor(accessor: Any, root_obj: Any) -> Any:
    """Evaluate an accessor (PathAccessor, callable, or static array) against root_obj."""
    if accessor is None:
        return None
    if isinstance(accessor, PathAccessor) or callable(accessor):
        return accessor(root_obj)
    return accessor
