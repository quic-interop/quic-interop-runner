from random_slugs import generate_slug as original_generate_slug

_used_slugs = set()


def generate_slug():
    while True:
        slug = original_generate_slug()
        if slug not in _used_slugs:
            _used_slugs.add(slug)
            return slug
