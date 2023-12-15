from django import template
from django.templatetags.static import static

from ..middleware import record_file_to_preload

register = template.Library()

@register.simple_tag(takes_context=True)
def http2static(context: dict, path: str, version: str=None) -> str:
    """
    same as static templatetag, except it saves the list of files used
    to request.to_preload in order to push them up to the user
    before they request it using HTTP2 push via the HTTP2PushMiddleware
    """
    url = f'{static(path)}?v={version}' if version else static(path)
    record_file_to_preload(context['request'], url)
    return url
