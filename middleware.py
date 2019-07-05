from django.conf import settings
from django.http import StreamingHttpResponse


PRELOAD_AS = {
    'js': 'script',
    'css': 'style',
    'png': 'image',
    'jpg': 'image',
    'jpeg': 'image',
    'webp': 'image',
    'svg': 'image',
    'gif': 'image',
    'ttf': 'font',
    'woff': 'font',
    'woff2': 'font'
}
PRELOAD_ORDER = {
    'css': 0,
    'ttf': 1,
    'woff': 1,
    'woff2': 1,
    'js': 2,
}


cached_preload_urls = {}
cached_response_types = {}



def record_file_to_preload(request, url):
    """save a staticfile to the list of files to push via HTTP2 preload"""
    if not hasattr(request, 'to_preload'):
        request.to_preload = set()

    request.to_preload.add(url)


def create_preload_header(urls, nonce=None, server_push=None):
    """Compose the Link: header contents from a list of urls"""
    without_vers = lambda url: url.split('?', 1)[0]
    extension = lambda url: url.rsplit('.', 1)[-1].lower()
    preload_priority = lambda url: PRELOAD_ORDER.get(url[1], 100)

    urls_with_ext = ((url, extension(without_vers(url))) for url in urls)
    sorted_urls = sorted(urls_with_ext, key=preload_priority)

    nonce = f'; nonce={nonce}' if nonce else ''
    if server_push is None:
        server_push = getattr(settings, 'HTTP2_SERVER_PUSH', False)

    nopush = '' if server_push else '; nopush'

    preload_tags = (
        f'<{url}>; rel=preload; crossorigin; as={PRELOAD_AS[ext]}{nonce}{nopush}'
        if ext in PRELOAD_AS else
        f'<{url}>; rel=preload; crossorigin{nonce}{nopush}'
        for url, ext in sorted_urls
    )
    return ', '.join(preload_tags)


def get_cached_response_type(request):
    global cached_response_types
    return cached_response_types.get(request.path, '')

def set_cached_response_type(request, response):
    global cached_response_types
    cached_response_types[request.path] = response['Content-Type'].split(';', 1)[0]

def get_cached_preload_urls(request):
    global cached_preload_urls

    
    
    if (getattr(settings, 'HTTP2_PRESEND_CACHED_HEADERS', False)
        and request.path in cached_preload_urls):
        
        return cached_preload_urls[request.path]

    return ()

def set_cached_preload_urls(request):
    global cached_preload_urls

    if (getattr(settings, 'HTTP2_PRESEND_CACHED_HEADERS', False)
        and getattr(request, 'to_preload', None)):
        
        cached_preload_urls[request.path] = request.to_preload


def should_preload(request):
    request_type = request.META.get('HTTP_ACCEPT', '')[:36]
    cached_response_type = get_cached_response_type(request)
    # print('REQUEST TYPE', request_type)
    # print('CACHED RESPONSE TYPE', cached_response_type)
    return (
        getattr(settings, 'HTTP2_PRELOAD_HEADERS', False)
        and 'text/html' in request_type
        and 'text/html' in cached_response_type
    )

def early_preload_response(request, get_response, nonce):
    def generate_response():
        yield ''
        response = get_response(request)
        set_cached_response_type(request, response)
        yield response.content

    response = StreamingHttpResponse(generate_response())
    response['Link'] = create_preload_header(request.to_preload, nonce)
    response['X-HTTP2-PRELOAD'] = 'early'

    # print('SENDING EARLY PRELOAD REQUEST', request.path, response['Content-Type'])
    return response

def late_preload_response(request, get_response, nonce):
    response = get_response(request)
    set_cached_response_type(request, response)

    if getattr(request, 'to_preload'):
        preload_header = create_preload_header(request.to_preload, nonce)
        response['Link'] = preload_header
        set_cached_preload_urls(request)
        response['X-HTTP2-PRELOAD'] = 'late'

    # print('SENDING LATE PRELOAD REQUEST', request.path, response['Content-Type'])
    return response

def preload_response(request, get_response):
    nonce = getattr(request, 'csp_nonce', None)
    cached_preload_urls = get_cached_preload_urls(request)
    if cached_preload_urls:
        request.to_preload = cached_preload_urls
        return early_preload_response(request, get_response, nonce)
    
    return late_preload_response(request, get_response, nonce)

def no_preload_response(request, get_response):
    response = get_response(request)
    set_cached_response_type(request, response)
    # print('SENDING NO PRELOAD REQUEST', request.path, response['Content-Type'])
    response['X-HTTP2-PRELOAD'] = 'off'
    return response


def HTTP2Middleware(get_response):
    def middleware(request):
        """Attach a Link: header containing preload links for every staticfile 
           referenced during the request by the {% http2static %} templatetag
        """
        if should_preload(request):
            return preload_response(request, get_response)
        return no_preload_response(request, get_response)
    return middleware
