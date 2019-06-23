# Django HTTP2 Middleware

<img src="https://blog.golang.org/h2push/serverpush.svg" height="200px" align="right">

This is a small middlware for Django v2.0+ to assist with generating preload headers for HTTP2-push, with support for using [`StreamingHttpResponse`](https://docs.djangoproject.com/en/2.2/ref/request-response/#django.http.StreamingHttpResponse) to send cached preload headers in advance of the actual response being generated. This allows nginx to serve push preload resources before
Django is even finished running the view and returning a response!

It's also fully compatible with [`django-csp`](https://django-csp.readthedocs.io/en/latest/configuration.html), it sends `request.csp_nonce` 
in preload headers correctly so that preloads aren't rejected by your CSP policy if they require a nonce.

## How it works

It works by providing a templatetag `{% http2static %}` that works just
like `{% static %}`, except it records all the urls on `request.to_preload` automatically as it renders the template.

Those urls are then transformed into an HTTP preload header which is attached to the response. When `settings.HTTP2_PRESEND_CACHED_HEADERS = True`, the first response's preload headers will be cached and automatically sent in advance during later requests (using [`StreamingHttpResponse`](https://docs.djangoproject.com/en/2.2/ref/request-response/#django.http.StreamingHttpResponse) to send them before the view executes) . Upstream servers like Nginx and CloudFlare will then use these headers to do HTTP2 server push, delivering the resources to clients before they are requested during browser parse & rendering.

<img src="https://i.imgur.com/sow31ar.png">

## Note about performance

While modern and shiny, this wont necessarily make your site faster. In fact, it can often make sites slower because later requests have the resources cached anyway, pushing uneeded resources on every request only wastes network bandwidth and hogs IO in some cases. Server push is best for sites where first-visit speed is a top priority.  It's up to you to toggle the options and find what the best tradeoffs are for your own needs.

## Usage
```html
<!-- Create a preload html tag at the top, not strictly necessary -->
<!-- but it's a good fallback in case HTTP2 is not supported -->
<link rel="preload" as="style" href="{% http2static 'css/base.css' %}" crossorigin nonce="{{request.csp_nonce}}">

...
<!-- Place the actual tag anywhere on the page, it will likely -->
<!-- already be pushed and downloaded by time the browser parses it. -->
<link rel="stylesheet" href="{% http2static 'css/base.css' %}" type="text/css" crossorigin nonce="{{request.csp_nonce}}">
```

## Install:

```bash
cd /opt/your-project/project-django/
git clone https://github.com/pirate/django-http2-middleware http2
```

Then add the following to your `settings.py`:
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
HTTP2_SERVER_PUSH = True

# optional recommended django-csp settings if you use CSP with nonce validation
CSP_DEFAULT_SRC = ("'self'", ...)
CSP_INCLUDE_NONCE_IN = ('default-src',  ...)
...
```

## Verifying it works

The cache warmup happens in three phases.  The first request to a given URL
after restarting runserver has no preload headers sent in advance (`off`), the second request has preload headers but only
attaches them after the response is generated (`late`).  And the third request
(and all requests after that) send the cached headers before the response is generated (`early`).

You can see the status by inspecting the `X-HTTP2-PRELOAD` header and the network requests waterfall in the dev tools:  
<img src="https://i.imgur.com/cHRF8ZF.png" width="300px">
<img src="https://i.imgur.com/g0ZU5u9.png" width="300px">

### `x-http2-preload: off`

<img src="https://i.imgur.com/sN5Rmjn.png" width="200px">

### `x-http2-preload: late`

<img src="https://i.imgur.com/pSOcGQy.png" width="200px">

### `x-http2-preload: early`

<img src="https://i.imgur.com/ouRu1rf.png" width="200px">




## Example Nginx Configuration

In order to use HTTP2 server push, you need a webserver in front of Django that reads
the <Link> preload headers and pushes the files.  Luckily, nginx can do this with only
one extra line of config.

```nginx
http2_push_preload                      on;
...

server {
  listen 443 ssl http2;
  ...
}
```

https://www.nginx.com/blog/nginx-1-13-9-http2-server-push/

<img src="https://www.nginx.com/wp-content/uploads/2018/02/http2-server-push-testing-results.png">
