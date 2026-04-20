# Issue #125: names referenced inside a decorator's call arguments
# should also be attributed to the decorated function, not only to the
# enclosing module scope. Mirrors FastAPI-style patterns like
# ``@router.get(path, dependencies=[Depends(Guard())])``.


def depends(callable_):
    return callable_


class Guard:
    def __init__(self):
        pass


def route(path, dependencies=None):
    def decorator(fn):
        return fn
    return decorator


@route("/open")
def open_route():
    return "ok"


@route("/secure", dependencies=[depends(Guard())])
def secure_route():
    return "ok"


@route("/mixed", dependencies=[depends(Guard())])
def mixed_route(token=depends(Guard())):
    return token


# Class decorators should receive the same treatment.


@route("/api")
class ApiHandler:
    def handle(self):
        return "ok"


@route("/api/secure", dependencies=[depends(Guard())])
class SecureApiHandler:
    def handle(self):
        return "ok"
