# core/cache.py
#
# Shared pygame resource cache. Previously copy-pasted into all three
# controllers; modes reach it via manager.cache.

import pygame


class ResourceCache:
    """
    Simple cache for pygame Surfaces and Fonts.
    Centralizing this avoids duplicate loads and reduces churn.
    """

    def __init__(self):
        self._images = {}  # (path, convert_alpha) -> Surface
        self._fonts = {}   # (name, size, bold) -> Font

    def get_font(self, name, size, bold=False):
        key = (name or "", int(size), bool(bold))
        f = self._fonts.get(key)
        if f is None:
            f = pygame.font.SysFont(name if name else None, int(size), bold=bool(bold))
            self._fonts[key] = f
        return f

    def get_image(self, path, convert_alpha=True):
        key = (path, bool(convert_alpha))
        surf = self._images.get(key)
        if surf is None:
            img = pygame.image.load(path)
            surf = img.convert_alpha() if convert_alpha else img.convert()
            self._images[key] = surf
        return surf

    def clear_images(self):
        self._images.clear()

    def clear_all(self):
        self._images.clear()
        self._fonts.clear()
