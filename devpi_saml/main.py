# -*- coding: utf-8 -*-
from datetime import datetime, timedelta, timezone

from devpi_server.keyfs import KeyFS
from devpi_server.log import threadlog
from devpi_tokens.restrictions import Restrictions, available_restrictions
from pluggy import HookimplMarker
from pyramid.httpexceptions import (HTTPForbidden, HTTPFound, HTTPOk,
                                    HTTPUnauthorized)
from pyramid.interfaces import IRequestExtensions, IRootFactory, IRoutesMapper
from pyramid.request import Request, apply_request_extensions
from pyramid.session import SignedCookieSessionFactory
from pyramid.threadlocal import RequestContext
from pyramid.traversal import DefaultRootFactory
from pyramid.view import view_config

CREATE_USERS_ON_DEMAND = True


def log(msg, *args):
    threadlog.debug(msg, *args)


log("Loading devpi_saml")

devpiserver_hookimpl = HookimplMarker("devpiserver")


def includeme(pyramid_config):
    pyramid_config.add_route("/+authcheck", "/+authcheck")
    pyramid_config.add_route("/+tokens", "/+tokens")
    pyramid_config.add_route(
        "/{user}/+tokens/ui", "/{user}/+tokens/ui", accept="text/html"
    )
    pyramid_config.add_route(
        "/{user}/+token-create/ui", "/{user}/+token-create/ui", accept="text/html"
    )
    pyramid_config.add_route(
        "/{user}/+token-delete/{id}/ui",
        "/{user}/+token-delete/{id}/ui",
        accept="text/html",
    )
    pyramid_config.scan()

    try:
        log("includeme pyramid_config")
        log(repr(pyramid_config))
        pyramid_config.include("pyramid_saml")
    except Exception as e:
        log("Could not load SAML")
        log(str(e))


@devpiserver_hookimpl
def devpiserver_pyramid_configure(config, pyramid_config):
    # Make the SAML config available where pyramid_saml will look for it
    if "pyramid_saml" not in pyramid_config.get_settings():
        pyramid_config.add_settings(pyramid_saml={})
    saml_settings = pyramid_config.get_settings().get("pyramid_saml")
    saml_settings.update({"index_route_name": "/"})
    if config.args.saml_path:
        saml_settings.update({"saml_path": config.args.saml_path})

    log("SAML settings: %r", saml_settings)

    key = config.get_derived_key(b"devpi_saml")
    pyramid_config.set_session_factory(SignedCookieSessionFactory(key))

    pyramid_config.include("devpi_saml.main")


@devpiserver_hookimpl
def devpiserver_add_parser_options(parser):
    group = parser.addgroup("SAML")
    group.addoption(
        "--saml-path",
        action="store",
        help="Folder which contains the SAML configuration",
    )


##############################################################################
# Authentication checks: use SSO cookie to identify logged in user
##############################################################################


class SAMLIdentity:
    def __init__(self, username):
        self.username = username
        self.groups = []


@devpiserver_hookimpl()
def devpiserver_get_identity(request, credentials):
    session = request.session
    log("Session %r", session)
    username = session.get("samlNameId")
    if not username:
        # Might still use other login means
        log("No SAML session found")
        return

    ensure_user(request)
    return SAMLIdentity(username)


def ensure_user(request):
    session = request.session
    username = session.get("samlNameId")
    xom = request.registry["xom"]

    model = xom.model
    log("Read-only? %r", model.keyfs._readonly)
    user = model.get_user(username)
    log("Looked up user %s: %r", username, user)
    if user is None:
        if CREATE_USERS_ON_DEMAND:
            try:
                model.create_user(username, None)
            except KeyFS.ReadOnly:
                model.keyfs.restart_as_write_transaction()
                model.create_user(username, None)
        else:
            raise HTTPForbidden("User is not authorized on this server")


##############################################################################
# Authcheck: used as an nginx route to see if the user is already logged in.
##############################################################################


@devpiserver_hookimpl(optionalhook=True)
def devpiserver_authcheck_always_ok(request):
    route = request.matched_route
    if route and route.name.endswith("/+api"):
        return True
    if route and route.name in ("/+login", "login", "logout"):
        return True
    if route and "+static" in route.name and "/+static" in request.url:
        return True
    if route and "+theme-static" in route.name and "/+theme-static" in request.url:
        return True


@devpiserver_hookimpl(optionalhook=True)
def devpiserver_authcheck_unauthorized(request):
    if not request.authenticated_userid:
        return True


def _auth_check_request(request):
    if devpiserver_authcheck_always_ok(request=request):
        request.log.debug(
            "Authcheck always OK for %s (%s)", request.url, request.matched_route.name
        )
        return HTTPOk()
    if not devpiserver_authcheck_unauthorized(request=request):
        request.log.debug(
            "Authcheck OK for %s (%s)", request.url, request.matched_route.name
        )
        return HTTPOk()
    request.log.debug(
        "Authcheck Unauthorized for %s (%s)", request.url, request.matched_route.name
    )
    user_agent = request.user_agent or ""
    if "devpi-client" in user_agent:
        # devpi-client needs to know for proper error messages
        return HTTPForbidden()
    return HTTPUnauthorized()


@view_config(route_name="/+authcheck")
def authcheck_view(context, request):
    routes_mapper = request.registry.getUtility(IRoutesMapper)
    root_factory = request.registry.queryUtility(
        IRootFactory, default=DefaultRootFactory
    )
    request_extensions = request.registry.getUtility(IRequestExtensions)
    url = request.headers.get("x-original-uri", request.url)
    orig_request = Request.blank(url, headers=request.headers)
    orig_request.log = request.log
    orig_request.registry = request.registry
    if request_extensions:
        apply_request_extensions(orig_request, extensions=request_extensions)
    info = routes_mapper(orig_request)
    (orig_request.matchdict, orig_request.matched_route) = (
        info["match"],
        info["route"],
    )
    root_factory = orig_request.matched_route.factory or root_factory
    orig_request.context = root_factory(orig_request)
    with RequestContext(orig_request):
        return _auth_check_request(orig_request)


##############################################################################
# Tokens: allow management of the tokens (with devpi_tokens)
##############################################################################


@view_config(
    route_name="/+tokens",
    request_method="GET",
)
def tokens_view(context, request):
    # Redirect to the per-user view, so that ACL checks work properly
    log("username %r", request.identity.username)
    url = request.route_url("/{user}/+tokens/ui", user=request.identity.username)
    return HTTPFound(location=url)


@view_config(
    route_name="/{user}/+tokens/ui",
    request_method="GET",
    permission="user_modify",
    renderer="templates/tokens.pt",
)
def user_tokens_view(context, request):
    session = request.session
    log("Session %r", session)

    tu = request.devpi_token_utility
    log("tu: %r", tu)
    tokens = tu.get_tokens_info(context.user)
    log("tu result: %r", tokens)

    parsed_tokens = []
    now = datetime.now(tz=timezone.utc)
    for token_id, token in tokens.items():
        expires = None
        expires_text = "-"
        for restriction in token.get("restrictions", []):
            if restriction.startswith("expires="):
                expires_ts = int(restriction.split("=")[1])
                expires = datetime.fromtimestamp(expires_ts, tz=timezone.utc)
                if expires - now < timedelta(days=7):
                    expires_text = expires.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    expires_text = expires.strftime("%Y-%m-%d")
        parsed_tokens.append(
            {
                "id": token_id,
                "expires": expires,
                "expires_text": expires_text,
                "delete_url": request.route_url(
                    "/{user}/+token-delete/{id}/ui",
                    user=request.identity.username,
                    id=token_id,
                ),
            }
        )
    parsed_tokens = list(sorted(parsed_tokens, key=lambda t: t["id"]))
    log("parsed_tokens %r", parsed_tokens)

    return dict(
        error=None,
        tokens=parsed_tokens,
        urls={
            "add_token": request.route_url(
                "/{user}/+token-create/ui", user=request.identity.username
            )
        },
    )


@view_config(
    route_name="/{user}/+token-create/ui",
    request_method="POST",
    permission="user_modify",
    renderer="templates/token-created.pt",
)
def user_token_create_view(context, request):
    restrictions = Restrictions()

    restriction = available_restrictions["expires"](None)
    restriction.validate_against_request(request)
    restrictions.add(restriction)

    tu = request.devpi_token_utility
    token = tu.new_token(context.user, restrictions)
    log("token result: %r", token)

    return dict(
        token=token,
        urls={
            "tokens": request.route_url(
                "/{user}/+tokens/ui", user=request.identity.username
            )
        },
    )


@view_config(
    route_name="/{user}/+token-delete/{id}/ui",
    request_method="POST",
    permission="user_modify",
)
def user_token_delete_view(context, request):
    tu = request.devpi_token_utility
    token_id = request.matchdict["id"]
    tu.remove_token(context.user, token_id)
    url = request.route_url("/{user}/+tokens/ui", user=request.identity.username)
    return HTTPFound(location=url)
