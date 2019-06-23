# Django HTTP2 Middleware

This is middlware for django to assist with generating preload headers for HTTP2-push, with support for using StreamingHttpResponse to send cached preload headers in advance of the actual response being generated. This allows nginx to serve push preload resources before
django is even finished running the view and returning a response!

It's also fully compatible with [`django-csp`](https://django-csp.readthedocs.io/en/latest/configuration.html), it sends `request.csp_nonce` 
in preload headers correctly so that preloads aren't rejected by your
csp policy if they require a nonce.

## How it works

It works by providing a templatetag `{% http2static %}` that works just
like `{% static %}`, except it records all the urls on `request.to_preload` automatically as it renders the template.

Those urls are then transformed into an HTTP preload header which is attached to the response. When `settings.HTTP2_PRESEND_CACHED_HEADERS = True`, the first response's preload headers will be cached and automatically sent in advance during later requests (using [`StreamingHttpResponse`](https://docs.djangoproject.com/en/2.2/ref/request-response/#django.http.StreamingHttpResponse) to send them before the view executes) . Upstream servers like Nginx and CloudFlare will then use these headers to do HTTP2 server push, delivering the resources to clients before they are requested during browser parse & rendering.

## Note about performance

While modern and shiny, this wont necessarily make your site faster. In fact, it can often make sites slower because later requests have the resources cached anyway, so pusing uneeded resources on every request only wastes network bandwidth and hogs IO. Server push is best for sites where first-visit speed is a top priority.  It's up to you to toggle the options and find what the best tradeoffs are for your own needs.

## Usage
```jija2
<!-- Create a preload html tag at the top, not strictly necessary -->
<!-- but it's a good fallback in case HTTP2 is not supported -->
<link rel="preload" as="style" href="{% http2static 'css/base.css' %}" crossorigin nonce="{{request.csp_nonce}}">

...
<!-- Place the actual tag anywhere on the page, it will likely -->
<!-- already be pushed and downloaded by time the browser parses it. -->
<link rel="stylesheet" href="{% http2static 'css/base.css' %}" type="text/css" crossorigin nonce="{{request.csp_nonce}}">
```

## Install:

cd /opt/your-project/project-django
git clone https://github.com/pirate/django-http2-middleware http2

Then add the following to `settings.py`
```python
# (adding "http2" to INSTALLED_APPS is not needed)

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        ...
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                ...
            ],
            'builtins': [
                ...
                'http2.templatetags',
            ],
        },
    },
    ...
]
MIDDLEWARE = [
    ...
    'csp.middleware.CSPMiddleware',  # (optional, must be above http2)
    'http2.middleware.HTTP2Middleware',
]

# attach any {% http2static %} urls in template as http preload header
HTTP2_PRELOAD_HEADERS = True

# cache first request's preload urls and send in advance on subsequent requests
HTTP2_PRESEND_CACHED_HEADERS = True

# allow upstream servers to server-push any files in preload headers
HTTP2_SERVER_PUSH = False

# optional recommended django-csp settings if you use CSP with nonce validation
CSP_DEFAULT_SRC = ("'self'", ...)
CSP_INCLUDE_NONCE_IN = ('default-src',  ...)
...
```

## Example Nginx Configuration:
```nginx
http2_push_preload                      on;
...

server {
  listen 443 ssl http2;
  ...
}
```
