devpi-saml: SAML authentication for devpi
=========================================

This plugin extends `devpi`_ with SAML Single Sign-On authentication.

It also extends devpi by protecting read-only access as well, similarly to
`devpi-lockdown`_ which does the same for the default password logins.

As SAML authentication can not be used on the command line, it also adds user
interface support for `devpi-tokens`_ to create tokens that can be used to log
into devpi.


Installation
------------

``devpi-saml`` needs to be installed alongside ``devpi-server``.

You can install it with::

    pip install devpi-saml

This package has only been tested with version 6.9 of ``devpi-server``.


Usage
-----

To lock down read access to devpi, you need a proxy in front of devpi which
can use the provided views to limit access.

This has been tested with nginx, where the `auth_request`_ module is required.
The config generation is not yet included in this plugin. Follow the
`devpi manual`_ for creating the nginx configuration, and then extend it
manually with the following.

.. code-block:: nginx

    # this redirects to the SSO view when not logged in
    error_page 401 = @error401;
    location @error401 {
        return 302 http://$host/sso?redirect=$request_uri;
    }

    # the location to check whether the provided infos authenticate the user
    location = /+authcheck {
        internal;

        proxy_pass_request_body off;
        proxy_set_header Content-Length "";
        proxy_set_header X-Original-URI $request_uri;
        proxy_set_header X-Outside-URL https://$host;
        proxy_pass http://localhost:3141;
    }

    # lock down everything by default
    auth_request /+authcheck;

    # pass on the various SSO routes without authentication
    location /sso {
        auth_request off;
        proxy_set_header X-Outside-URL https://$host;
        proxy_pass http://localhost:3141;
    }
    location /slo {
        auth_request off;
        proxy_set_header X-Outside-URL https://$host;
        proxy_pass http://localhost:3141;
    }
    location /acs {
        auth_request off;
        proxy_set_header X-Outside-URL https://$host;
        proxy_pass http://localhost:3141;
    }
    location /sls {
        auth_request off;
        proxy_set_header X-Outside-URL https://$host;
        proxy_pass http://localhost:3141;
    }
    location /metadata {
        auth_request off;
        proxy_set_header X-Outside-URL https://$host;
        proxy_pass http://localhost:3141;
    }

    # pass on /+api without authentication check for URL endpoint discovery
    location ~ /\+api$ {
        auth_request off;
        proxy_set_header X-Outside-URL https://$host;
        proxy_pass http://localhost:3141;
    }

    # pass on /+static without authentication check for browser access to css etc
    location /+static/ {
        auth_request off;
        proxy_set_header X-Outside-URL https://$host;
        proxy_pass http://localhost:3141;
    }
    location = /favicon.ico {
        auth_request off;
        proxy_set_header X-Outside-URL https://$host;
        proxy_pass http://localhost:3141;
    }

    # try serving static files directly
    location ~ /\+f/ {
        # workaround to pass non-GET/HEAD requests through to the named location below
        error_page 418 = @proxy_to_app;
        if ($request_method !~ (GET)|(HEAD)) {
            return 418;
        }

        expires max;
        try_files /+files$uri @proxy_to_app;
    }

    # try serving docs directly
    location ~ /\+doc/ {
        # if the --documentation-path option of devpi-web is used,
        # then the root must be set accordingly here
        # root /tmp/home/mydevpiserver;
        try_files $uri @proxy_to_app;
    }


.. _devpi: https://github.com/devpi/devpi
.. _devpi-lockdown: https://github.com/devpi/devpi-lockdown
.. _devpi-tokens: https://github.com/devpi/devpi-tokens
.. _auth_request: http://nginx.org/en/docs/http/ngx_http_auth_request_module.html
