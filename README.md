# Django HTTP2

```html
<script src="{% http2static 'js/jquery.min.js' %}"></script>
<!-- Preload header for js/jquery.min.js will be automatically attached to response -->
```

<img src="https://i.imgur.com/ouRu1rf.png" height="250px" align="right">

This is a small middlware for Django v2.0+ to automatically generate preload headers from staticfiles used in template rendering, with support for using [`StreamingHttpResponse`](https://docs.djangoproject.com/en/2.2/ref/request-response/#django.http.StreamingHttpResponse) to send cached preload headers in advance of the actual response being generated. The preload headers alone provide large speed boost, but pre-sending the cached headers in advance of view execution is the real advantage that this library provides.

It's also built to support modern security features like [Content Security Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Security-Policy) using [`django-csp`](https://django-csp.readthedocs.io/en/latest/configuration.html), it sends `request.csp_nonce`
in preload headers correctly so that preloads aren't rejected by your CSP policy if they require a nonce. Support for automatically generating and attaching CSP hashes for staticfiles and inline blocks is also planned in the near future.

---

## How it works

It works by providing a templatetag `{% http2static %}` that serves as a drop-in replacement for `{% static %}`, except it records all the urls used while rendering the template in `request.to_preload`.

The http2 middleware then transforms the list of `to_preload` urls into a full HTTP preload header, which is then attached to the response. When `settings.HTTP2_PRESEND_CACHED_HEADERS = True`, the first response's preload headers will be cached and automatically sent in advance during later requests (using [`StreamingHttpResponse`](https://docs.djangoproject.com/en/2.2/ref/request-response/#django.http.StreamingHttpResponse) to send them before the view executes). Upstream servers like Nginx and CloudFlare can then use these headers to do HTTP2 server push, delivering the resources to clients before they are requested during browser parse & rendering.  With [TCP fast-open](https://en.wikipedia.org/wiki/TCP_Fast_Open), [TLS 1.3](https://blog.cloudflare.com/rfc-8446-aka-tls-1-3/), and [HTTP2 server push](https://www.smashingmagazine.com/2017/04/guide-http2-server-push/), it's now possible to have entire pageloads with only 1 round-trip, now all we need are cache-digests and QUIC and then we'll be at web nirvana 🎂.

<img src="https://i.imgur.com/sow31ar.png" width="70%"><img src="https://blog.golang.org/h2push/serverpush.svg" width="29%">

### HTTP2 server-push

When preload headers are sent fast and `HTTP2_SERVER_PUSH = True` is enabled in `settings.py`, upstream servers like Nginx or Cloudflare HTTP2 will usually finish server pushing all the page resources not only before the browser requests them, but even before the view is finished executing, providing a 100ms+ headstart to static file loading in some cases. When enabled it's very cool to look at the network waterfall visualization and see your page's statcifiles finish loading together, a full 50ms+ before the HTML is even returned from Django!

Unfortunately, while shiny and exciting, this wont necessarily make your site faster for real-world users. In fact, it can sometimes make sites slower because after the first visit, users have most of the resources cached anyway, and pushing uneeded files on every request can waste network bandwidth and use IO & CPU capacity that otherwise would've gone towards loading the actual content.  You should toggle the config options while testing your project to see if server push provides real-world speed gains, or use the [recommended settings](#Recommended-Settings) listed below that provide speed gains in most cases without the risk of wasting bandwidth to push uneeded resources. There are some cases where HTTP2 push is still worth it though, e.g. if you have to push a small bundle of static files for first paint and most of your users are first-time visitors without your site cached.

HTTP2 server-push will eventually become the optimal method of page delivery once cache-digests are released (improving both latency and bandwidth use).  Read these articles and the links within them to learn more about HTTP2, server push, and why cache digests are an important feature needed to make server-push worth it:

 - https://http2.github.io/faq/#whats-the-benefit-of-server-push
 - https://calendar.perfplanet.com/2016/cache-digests-http2-server-push/
 - https://httpwg.org/http-extensions/cache-digest.html#introduction

This library is still useful without server push enabled though, as it's primary function is to collect statifiles and send them as `<Link>` preload headers in parallel *before the Django views finish executing*, which can provide a 100ms+ headstart for the browser to start loading page content in many cases. The optimal recommended settings for maximum speed gain (as of 2019/07) are to send preload headers, cache them and send them in advance, but don't enable `HTTP2_SERVER_PUSH` until cache-digest functionality is released in most browsers.

## Install:

1. Install the `django-http2` package using your package manager of choice:
```bash
pip install django-http2
```

1. Add `http2.middleware.HTTP2Middleware` to your `MIDDLEWARE` list in `settings.py`:
```python
MIDDLEWARE = [
    ...
    'csp.middleware.CSPMiddleware',       # (optional if you use django-csp, it must be above the http2 middleware)
    'django_http2.middleware.HTTP2Middleware',   # (add the middleware at the end, but before gzip)
]
# (adding "http2" to INSTALLED_APPS is not needed)
```

1. Add the required configuration options to your `settings.py`:
```python
HTTP2_PRELOAD_HEADERS = True
HTTP2_PRESEND_CACHED_HEADERS = True
HTTP2_SERVER_PUSH = False
```

1. (Optional if using `django-csp`) Include nonces on any desired resource types in `settings.py`:
Generated preload headers will automatically include this nonce using `{{request.csp_nonce}}`.
```python
# add any types you want to use with nonce-validation (or just add it to the fallback default-src)
CSP_DEFAULT_SRC = ("'self'", ...)
CSP_INCLUDE_NONCE_IN = ('default-src',  ...)
```

## Usage

Just use the `{% http2static '...' %}` tag instead of `{% static '...' %}` anytime you want to have a resource preloaded.

```html
<!-- It's still a good idea to put normal html preload link tags at the top of your templates in addition to using the auto-generated HTTP headers, though it's not strictly necessary -->
<link rel="preload" as="style" href="{% http2static 'css/base.css' %}" crossorigin nonce="{{request.csp_nonce}}">
<link rel="preload" as="script" href="{% http2static 'vendor/jquery-3.4.1/jquery.min.js' %}" crossorigin nonce="{{request.csp_nonce}}">

...
<!-- Place the actual tags anywhere on the page, they will likely already be pushed and downloaded by time the browser parses them. -->
<link rel="stylesheet" href="{% http2static 'css/base.css' %}" type="text/css" crossorigin nonce="{{request.csp_nonce}}">
<script src="{% http2static 'vendor/jquery-3.4.1/jquery.min.js' %}" type="text/javascript" crossorigin nonce="{{request.cscp_nonce}}"></script>
```

Don't use `{% http2static %}` for everything, just use it for things in the critical render path that are needed for the initial pageload.  It's best used for CSS, JS, fonts, and icons required to render the page nicely, but usually shouldn't be used for  non-critical footer scripts and styles, async page content, images, video, audio, or other media.


## Configuration

### Recommended Settings

These settings provide the most speed gains for 90% of sites, though it's worth testing all the possibilities to see the real-world results for your project.

```python
HTTP2_PRELOAD_HEADERS = True
HTTP2_PRESEND_CACHED_HEADERS = True
HTTP2_SERVER_PUSH = False
```
### `django-http2-middleware` Configuration

#### `HTTP2_PRELOAD_HEADERS`
*Values:* [`True`]/`False`

Attach any `{% http2static %}` urls used templates in an auto-generated HTTP preload header on the response.
Disable this to turn off preload headers and disable the middleware entirely, this also prevents both header caching and http2 server push.

#### `HTTP2_PRESEND_CACHED_HEADERS`
*Values:* [`True`]/`False`

Cache first request's preload urls and send in advance on subsequent requests.
Eanble this to cache the first request's generated preload headers and use [`StreamingHttpResponse`](https://docs.djangoproject.com/en/2.2/ref/request-response/#django.http.StreamingHttpResponse) on subsequent requests to send the headers early before the view starts executing.  Disable this to use normal HTTPResponses with the preload headers attached at the end of view execution.

#### `HTTP2_SERVER_PUSH`
*Values:* `True`/[`False`]

Allow upstream servers to server-push any files in preload headers.
Disable this to add `; nopush` to all the preload headers to prevent upstream servers from pushing resources in advance.
Keeping this set to `False` is recommended until cache-digests are sent by most browsers.

### `django-csp` Configuration

There are many ways to implement Content Security Policy headers and nonces with Django,
the most popular for django is [`django-csp`](https://github.com/mozilla/django-csp),
which is library maintained by Mozilla. This library is built to be compatible
with Mozilla's `django-csp`, but it's not required to use both together.  You can find more info about
configuring Django to do CSP verification here:

- https://django-csp.readthedocs.io/en/latest/configuration.html#policy-settings
- https://content-security-policy.com/
- https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Security-Policy

### Webserver Configuration

In order to use HTTP2 server push, you need a webserver in front of Django that reads
the <Link> preload headers and pushes the files.  Cloudflare has a GUI [control panel option](https://www.cloudflare.com/website-optimization/http2/serverpush/) to enable server push,
 and nginx can do it with only one extra line of config:

```nginx
server {
    listen 443 ssl http2;
    http2_push_preload on;  # nginx will automatically server-push anything specified in preload headers
    ...
}
```

See more info and nginx http2 options here:

 - https://www.nginx.com/blog/nginx-1-13-9-http2-server-push/
 - http://nginx.org/en/docs/http/ngx_http_v2_module.html


## Verifying it works

<img src="https://i.imgur.com/cHRF8ZF.png" width="150px" align="right">

Responses can be served in three different ways when using `django-http2-middleware`. You can inspect which way is
used for a given response by looking at the `x-http2-preload` header attached to the response.
If all the options are enabled, it takes two initial requests after enabling the middleware and starting Django for the cache to warm up, one to detect the content type, and one to build the list of resource URLs used by the template:

1. The first request to a given URL has no preload headers sent in advance (`x-http2-preload: off`). It's used to confirm that the request and response are `Content-Type: text/html` and not a JSON API request, file download, or other non-html type that shouldn't have preload headers attached.
2. The second request has preload headers but only attaches them after the response is generated (`x-http2-preload: late`). It's used build the initial cache of preload urls for the given `request.path` by collecting urls used by `{% http2static %}` tags during template rendering.
3. If `HTTP2_PRESEND_CACHED_HEADERS = True`, the third request (and all requests after that) send the cached headers immediately before the response is generated (`x-http2-preload: early`). If presending cached headers is disabled, then `StreamingHttpResponse` wont be used to pre-send headers before the view, and preload headers will be attached after the response as usual in `x-http2-preload: late` mode.

Start runserver behind nginx and reload your page 4 times while watching the dev console to confirm the cache warms up properly and later requests receive server-pushed resources.  If everyting is working correctly,
the third pageload and all subsequent loads by all users should show up with the `x-http2-preload: early` response header, and pushed resources should appear significantly earlier in the network timing watefall view.

You can inspect the preload performance of a given page and confirm it matches what you expect for its `x-http2-preload` mode using the network requests waterfall graph in the Chrome/Firefox/Safari dev tools.


|     `x-http2-preload: off`     |         `x-http2-preload: late`        |       `x-http2-preload: early`        |
| ------------------------------ | -------------------------------------- | ------------------------------------- |
| ![](https://i.imgur.com/sN5Rmjn.png) | ![](https://i.imgur.com/pSOcGQy.png) | ![](https://i.imgur.com/ouRu1rf.png) |
|         Requires:              |             Requires:                  |             Requires:                 |
| `HTTP2_PRELOAD_HEADERS = True` |  `HTTP2_PRELOAD_HEADERS = True`        | `HTTP2_PRELOAD_HEADERS = True`        |
|                                |  `HTTP2_PRESEND_CACHED_HEADERS = True` | `HTTP2_PRESEND_CACHED_HEADERS = True` |
|                                |                                        | `HTTP2_SERVER_PUSH = True`            |

If you set `HTTP2_PRESEND_CACHED_HEADERS = True` and `HTTP2_SERVER_PUSH = False`, responses will all be sent in `x-http2-preload: late` mode, which is the recommended mode until cache digests become available in most browsers.

<div align="center">

<img src="https://i.imgur.com/g0ZU5u9.png" width="25%"><img src="https://www.nginx.com/wp-content/uploads/2018/02/http2-server-push-testing-results.png" width="40%">

</div>

## Further Reading

### Docs & Articles

 - https://dexecure.com/blog/http2-push-vs-http-preload/
 - https://www.keycdn.com/blog/http-preload-vs-http2-push
 - https://symfony.com/doc/current/web_link.html
 - https://www.smashingmagazine.com/2017/04/guide-http2-server-push/
 - http2.github.io/faq/#whats-the-benefit-of-server-push
 - https://calendar.perfplanet.com/2016/cache-digests-http2-server-push
 - https://httpwg.org/http-extensions/cache-digest.html#introduction
 - https://django-csp.readthedocs.io/en/latest/configuration.html#policy-settings
 - https://content-security-policy.com
 - htts://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Content-Security-Policy

### Similar Projects

After making my own solution I discovered great minds think alike, and a few people have done exactly the same thing before me already!
It's crazy how similarly we all chose to implement this, everyone used a drop-in replacement for `{% static %}`, I guess it goes to show
that Django is particularly designed well in this area, because there's one obvious way to do things and everyone independently figured it out and implemented robust solutions in <200LOC.

- https://github.com/ricardochaves/django_http2_push
- https://github.com/fladi/django-static-push
- https://github.com/DistPub/nginx-http2-django-server-push

However, none of these support CSP policies (which require adding nonces to the preload headers), or use [`StreamingHttpResponse`](https://docs.djangoproject.com/en/2.2/ref/request-response/#django.http.StreamingHttpResponse)
to send push headers before the view executes, so in some ways this project takes adventage of the available HTTP2 speed-up methods to the fullest degree out of the 4.

### Project Status

Consider this library "beta" software, still rough in some areas, but used in production for 6+ months on several projects. It's not on PyPi tet, I'll publish it once it's nicer and has more tests.  For now it should be cloned into your Django folder, or used piecewise as inspiration for your own code.

Once HTTP2 [cache digests](https://httpwg.org/http-extensions/cache-digest.html) are finalized, server push will ~~invariably~~(2020 Edit: [lol](https://groups.google.com/a/chromium.org/g/blink-dev/c/K3rYLvmQUBY/m/vOWBKZGoAQAJ)) become the fastest way to deliver assets, and this project will get more of my time as we integrate it into all our production projects at @Monadical-SAS.  To read more about why cache digests are critical to HTTP2 server push actually being useful, this article is a great resource:

<div align="center">

<img src="https://i.imgur.com/fyFvPak.png" width="400px"><br/>

["Cache Digests: Solving the Cache Invalidation Problem of HTTP/2 Server Push to Reduce Latency and Bandwidth"](https://calendar.perfplanet.com/2016/cache-digests-http2-server-push/) by Sebastiaan Deckers

</div>

## Bonus Material

Did you know you can run code *after a Django view returns a response* without using Celery, Dramatiq, or another background worker system?
Turns out it's trivially easy, but very few people know about it.

```python
def my_view(request):
    ...
    return HttpResponseWithCallback(..., callback=some_expensive_function)

class HttpResponseWithCallback(HttpResponse):
    def __init__(self, *args, **kwargs):
        self.callback = kwargs.pop('callback', None)
        super().__init__(*args, **kwargs)

    def close(self):
        super().close()
        self.callback and self.callback(response=self)
```


In small projects it's perfect for sending signup emails, tracking analytics events, writing to files, or any other CPU/IO intensive task that you don't want to block the user on.
In large projects, this is an antipattern because it encourages putting big blocking IO or CPU operations in these "fake" async request callbacks. The callbacks don't actually run asyncronously (like Celery), they don't provide any free performance improvement on the main server thread, in they just hide some operations outside of the normal request/response lifecycle and make it hard to track down latency issues. You probably don't want to block main Django worker threads with things that would be better handled in the background, as it'll greatly reduce the number of simultaneous users your servers can handle.

For a full example demonstrating this library and more, check out this gist: [django_turbo_response.py](https://gist.github.com/pirate/79f84dfee81ba0a38b6113541e827fd5).
