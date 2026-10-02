"""Scratch audit: introspect the live FastAPI app for real auth coverage."""

import sys

sys.path.insert(0, "src")

from fastapi.routing import APIRoute  # noqa: E402

from api.main import app  # noqa: E402

SECURITY_FNS = {
    "get_current_user",
    "_role_checker",
    "_permission_checker",
}
PUBLIC_OK = {
    ("POST", "/auth/register"),
    ("POST", "/auth/login"),
    ("GET", "/health"),
    ("GET", "/"),
    ("GET", "/dashboard"),
}


def collect(dependant, found):
    stack = [dependant]
    while stack:
        current = stack.pop()
        for dep in getattr(current, "dependencies", []) or []:
            call = getattr(dep, "call", None)
            name = getattr(call, "__name__", None)
            if name in SECURITY_FNS:
                found.add(name)
            for cell in getattr(call, "__closure__", None) or []:
                inner = cell.cell_contents
                if callable(inner) and getattr(inner, "__name__", "") in SECURITY_FNS:
                    found.add(inner.__name__)
            sub = getattr(dep, "dependant", None) or getattr(call, "dependency", None)
            if sub is not None:
                stack.append(sub)


rows = []


def walk(routes, prefix=""):
    """Flatten routes, descending into routers this FastAPI version wraps."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        nested = (
            getattr(route, "routes", None)
            or getattr(getattr(route, "original_router", None), "routes", None)
            or getattr(getattr(route, "router", None), "routes", None)
            or []
        )
        if nested:
            yield from walk(nested, prefix)


for route in walk(app.routes):
    found = set()
    collect(route.dependant, found)
    perms = []
    for dep in route.dependant.dependencies:
        for cell in getattr(dep.call, "__closure__", None) or []:
            inner = cell.cell_contents
            if isinstance(inner, str):
                perms.append(inner)
    rows.append(
        (
            ",".join(sorted(route.methods)),
            route.path,
            route.name,
            sorted(found),
            sorted(set(perms)),
        )
    )

print(f"{'method':14} {'path':46} {'handler':32} guards")
print("-" * 130)
unguarded = []
for methods, path, name, found, _perms in rows:
    key = (methods.split(",")[0], path)
    flag = ""
    if not found:
        if key in PUBLIC_OK:
            flag = "   (public)"
        else:
            flag = "   <== NO AUTH DEP"
            unguarded.append((methods, path, name))
    print(f"{methods:14} {path:46} {name:32} {','.join(found) or '-'} {flag}")

print(f"\ntotal routes: {len(rows)}")
print(f"routes with no auth dependency: {len(unguarded)}")
for m, p, n in unguarded:
    print("   ", m, p, n)
