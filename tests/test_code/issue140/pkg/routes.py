from pkg.schemas import LoginRequest, TokenResponse, make_router

# A module-level use of an imported name. Nothing inside this module uses
# `make_router`, so the module's edge to it is the only record of the call.
router = make_router()


def login(req: LoginRequest):
    return TokenResponse()
