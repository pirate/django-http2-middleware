# Django HTTP2 Middleware

<img src="https://blog.golang.org/h2push/serverpush.svg" height="200px" align="right">

This is a small middlware for Django v2.0+ to automatically generate preload headers from staticfiles used in template rendering, with support for using [`StreamingHttpResponse`](https://docs.djangoproject.com/en/2.2/ref/request-response/#django.http.StreamingHttpResponse) to send cached preload headers in advance of the actual response being generated. The preload headers alone provide large speed boost, but pre-sending the cached headers in advance of view execution is the real advantage that this library provides compared to other libraries. 

It's also fully compatible with [`django-csp`](https://django-csp.readthedocs.io/en/latest/configuration.html), it sends `request.csp_nonce` 
in preload headers correctly so that preloads aren't rejected by your CSP policy if they require a nonce. Support for automatically generating and attaching CSP hashes for staticfiles and inline blocks is also planned in the near future.

**A note about HTTP2 server-push:**  
As an optional bonus, when preload headers are sent early and `HTTP2_SERVER_PUSH = True` in settings.py, upstream servers like Nginx or Cloudflare HTTP2 will usually finish server pushing all the page resources not only before the browser requests them, but even before the view is finished executing, providing a 100ms+ headstart to static file loading in some cases. When enabled it's very cool to look at the network waterfall visualization and see your page's statcifiles finish loading together, a full 50ms before the HTML is even returned from Django!

HTTP2 server-push will become the optimal method of page delivery for both latency and bandwidth once cache-digests are released.  Until then, it remains a novel toy that isn't recommended in most cases, but is fun to play with if you like deploying the most cutting edge tech you can. Read more about HTTP2 and server push here:

 - https://http2.github.io/faq/#whats-the-benefit-of-server-push
 - https://calendar.perfplanet.com/2016/cache-digests-http2-server-push/
 - https://httpwg.org/http-extensions/cache-digest.html#introduction

This library is still useful without server push enabled though, as it's primary function is to collect statifiles and send them as `<Link>` preload headers in parallel *before the Django views finish executing*, which can provide a 100ms+ headstart for the browser to start loading page content in many cases. The optimal recommended settings for maximum speed gain (as of 2019/07) are to send preload headers, cache them and send them in advance, but don't enable `HTTP2_SERVER_PUSH` until cache-digest functionality is released in most browsers:

```python
HTTP2_PRELOAD_HEADERS = True
HTTP2_PRESEND_CACHED_HEADERS = True
HTTP2_SERVER_PUSH = False
```

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
HTTP2_SERVER_PUSH = False   # False is recommended until cache-digests are sent by most browsers

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

Start runserver behind nginx and reload your page 3 times while watching the dev console.  If everyting is working correctly,
the third pageload and all subsequent loads by all users should show up with the `x-http2-preload: early` response header and have all it's `{% http2static url %}` resources served in advance via HTTP2 server push.

You can see the preload status of a given page by inspecting the `X-HTTP2-PRELOAD` response header, and the network requests waterfall in the dev tools:  
<img src="https://i.imgur.com/cHRF8ZF.png" width="300px">
<img src="https://i.imgur.com/g0ZU5u9.png" width="300px">

| `x-http2-preload: off`  | `x-http2-preload: late` | `x-http2-preload: early` |
| ------------- | ------------- | ------------- |
| ![](https://i.imgur.com/sN5Rmjn.png)  | ![](https://i.imgur.com/pSOcGQy.png)  | ![](https://i.imgur.com/ouRu1rf.png)  |
| Requires `HTTP2_PRELOAD_HEADERS = True`  | Requires `HTTP2_PRESEND_CACHED_HEADERS = True`  | Requires `HTTP2_SERVER_PUSH = True`  |




## Example Nginx Configuration

In order to use HTTP2 server push, you need a webserver in front of Django that reads
the <Link> preload headers and pushes the files.  Luckily, nginx can do this with only
one extra line of config.

```nginx
http2_push_preload on;  # nginx will automatically server-push anything specified in the preload header
...

server {
    listen 443 ssl http2;
    ...
    location / {
        proxy_pass http://127.0.0.1:8000;
        ...
    }
}
```

https://www.nginx.com/blog/nginx-1-13-9-http2-server-push/

<img src="https://www.nginx.com/wp-content/uploads/2018/02/http2-server-push-testing-results.png">

## Further Reading

After making my own solution I discovered great minds think alike, and a few people have done exactly the same thing before me already!
It's crazy how similarly we all chose to implement this, everyone used a drop-in replacement for `{% static %}`, I guess it goes to show
that Django is particularly designed well in this area, because there's one obvious way to do things and everyone independently figured it out and implemented robust solutions in <200LOC.

- https://github.com/ricardochaves/django_http2_push
- https://github.com/fladi/django-static-push
- https://github.com/DistPub/nginx-http2-django-server-push

However, none of these support CSP policies (which require adding nonces to the preload headers), or use [`StreamingHttpResponse`](https://docs.djangoproject.com/en/2.2/ref/request-response/#django.http.StreamingHttpResponse)
to send push headers before the view executes, so I think while not complete or "production-ready", this project takes adventage of the available speed-up methods to the fullest degree out of the 4.

Once HTTP2 [cache digests](https://httpwg.org/http-extensions/cache-digest.html) are finalized, server push will invariably become the fastest way to deliver assets, and this project will get more of my time as we integrate it into all our production projects at @Monadical-SAS.  To read more about why cache digests are critical to HTTP2 server push actually being useful, this article is a great resource:  

<div align="center">
    
<img src="https://i.imgur.com/fyFvPak.png" width="500px"><br/>

["Cache Digests: Solving the Cache Invalidation Problem of HTTP/2 Server Push to Reduce Latency and Bandwidth"](https://calendar.perfplanet.com/2016/cache-digests-http2-server-push/) by Sebastiaan Deckers

</div>

## Bonus Material

Did you know you can run code *after a Django view returns a response* without using Celery, Dramatiq, or another background worker system?
Turns out it's trivially easy, but very few people know about it: https://gist.github.com/pirate/c4deb41c16793c05950a6721a820cde9

It's perfect for sending signup emails, tracking analytics events, writing to files, or any other CPU/IO intensive task that you don't want to block the user on.
