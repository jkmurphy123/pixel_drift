# modes/imaginary_library_mode.py
#
# Imaginary Library mode for pixel_drift.
#
# Presents one forbidden medieval manuscript at a time.  Cover images are
# supplied by the user; all textual data lives in data/imaginary_library/books.json.
# No network calls are made at runtime.
#
# Config keys (see designs/LIBRARY_DESIGN.md):
#   - image_folder          folder containing 800x1200 cover images
#   - books_file            path to books.json (default: data/imaginary_library/books.json)
#   - dwell_seconds         seconds per book (default: 180)
#   - match_by              "filename" uses cover_image field; "index" uses alpha sort
#   - portrait_layout       if True, stack cover above text panel (default: False)
#   - placeholder_color     [r,g,b] base color for generated missing covers
#   - show_tags             render tag pills (default: True)
#   - show_review           render review excerpt (default: True)
#   - font_name             system font name or path to .ttf/.otf
#   - title_font_size       default 48
#   - body_font_size        default 48
#   - small_font_size       default 36
#   - tag_font_size         default 32
#
# Book JSON fields:
#   - detailed_history_1 .. detailed_history_6
#     Each non-empty field is shown in turn on the right-hand panel, with a
#     short fade between fields.  Blank fields are skipped.  The fields loop
#     until dwell_seconds expires and the next book is shown.

import hashlib
import json
import os

import pygame


class ImaginaryLibraryMode:
    """Scene-style mode that cycles through imaginary books/manuscripts."""

    # Supported image extensions for index matching.
    IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")

    # Transition between books, in seconds.
    CROSSFADE_SECONDS = 0.8

    # Transition between history fields of the same book, in seconds.
    FIELD_FADE_SECONDS = 0.7

    def __init__(self, config: dict):
        # --- behavior ---
        self.dwell_seconds = float(config.get("dwell_seconds", 180.0))
        self.image_folder = str(config.get("image_folder", "assets/books"))
        self.books_file = str(config.get("books_file", "data/imaginary_library/books.json"))
        self.match_by = str(config.get("match_by", "filename")).lower()
        self.portrait_layout = bool(config.get("portrait_layout", False))
        self.show_tags = bool(config.get("show_tags", True))
        self.show_review = bool(config.get("show_review", True))

        # --- presentation ---
        self.font_name = config.get("font_name", None)
        self.title_font_size = int(config.get("title_font_size", 48))
        self.body_font_size = int(config.get("body_font_size", 48))
        self.small_font_size = int(config.get("small_font_size", 36))
        self.tag_font_size = int(config.get("tag_font_size", 32))

        raw_color = config.get("placeholder_color", [40, 35, 55])
        self.placeholder_color = tuple(int(c) for c in raw_color)

        # --- colors (dark parchment / forbidden-library theme) ---
        self._bg = (22, 18, 15)
        self._title = (225, 215, 185)
        self._subtitle = (165, 155, 135)
        self._body = (205, 198, 180)
        self._dim = (130, 122, 110)
        self._accent = (180, 145, 80)
        self._tag_bg = (55, 48, 42)
        self._tag_fg = (185, 178, 165)
        self._shadow = (8, 6, 5)

        # --- runtime ---
        self.manager = None
        self.w = 0
        self.h = 0

        self.books = []
        self.book_index = 0
        self._image_files = []  # sorted image filenames when match_by == "index"
        self._error_message = None

        # Book-level timer and cross-fade.
        self._timer = 0.0
        self._book_transition = 0.0  # 1.0 = current book fully visible

        # History-field cycling within the current book.
        self._field_index = 0
        self._field_timer = 0.0
        self._field_transition = 0.0  # 1.0 = current field fully visible
        self._field_texts = []  # non-blank history strings for current book
        self._next_field_texts = []  # non-blank history strings for next book

        self._panel_rect = pygame.Rect(0, 0, 0, 0)

        # Cached surfaces for the current and next books.
        self._current_cover = None
        self._next_cover = None
        self._current_fields = []  # list of rendered field surfaces
        self._next_fields = []
        self._cached_book_index = -1
        self._cached_size = (0, 0)

        # Font cache, including optional path-loaded fonts.
        self._font_cache = {}

    # ---------------- lifecycle ----------------

    def enter(self, manager):
        self.manager = manager
        self.w, self.h = manager.screen.get_size()
        self._load_books()
        self._scan_image_folder()

        self.book_index = 0
        self._timer = 0.0
        self._book_transition = 0.0
        self._field_index = 0
        self._field_timer = 0.0
        self._field_transition = 0.0
        self._field_texts = []
        self._next_field_texts = []

        if self.books:
            self._prepare_book(self.book_index)

    def exit(self):
        # Release all surfaces and references so GC can reclaim memory.
        self._current_cover = None
        self._next_cover = None
        self._current_fields = []
        self._next_fields = []
        self._field_texts = []
        self._next_field_texts = []
        self._font_cache.clear()
        self.books = []
        self._image_files = []
        self.manager = None

    def handle_event(self, event):
        # In single-mode test runs the controller passes arrow keys through.
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RIGHT and self._book_transition == 0.0 and self._field_transition == 0.0:
                self._advance_book(+1)
                return
            if event.key == pygame.K_LEFT and self._book_transition == 0.0 and self._field_transition == 0.0:
                self._advance_book(-1)
                return

    def update(self, dt: float):
        if self.manager is None:
            return

        # Handle resolution changes (hotplug, rotation, resize in windowed mode).
        w2, h2 = self.manager.screen.get_size()
        if (w2, h2) != (self.w, self.h):
            self.w, self.h = w2, h2
            self._invalidate_cache()
            if self.books:
                self._prepare_book(self.book_index)
            return

        if not self.books:
            return

        # Cross-fade between books.
        if self._book_transition > 0.0:
            self._book_transition -= dt / self.CROSSFADE_SECONDS
            if self._book_transition <= 0.0:
                self._book_transition = 0.0
                # Promote next to current.
                self._current_cover = self._next_cover
                self._current_fields = self._next_fields
                self._field_texts = self._next_field_texts
                self._next_cover = None
                self._next_fields = []
                self._next_field_texts = []
                self._field_index = 0
                self._field_timer = 0.0
                self._field_transition = 0.0
                self._timer = 0.0
            return

        # Book dwell timer.
        self._timer += dt

        # No history fields: just show the metadata for the full dwell.
        if not self._field_texts:
            if self._timer >= self.dwell_seconds:
                self._advance_book(+1)
            return

        num_fields = len(self._field_texts)
        field_duration = self.dwell_seconds / max(num_fields, 1)

        self._field_timer += dt

        # Advance to the next book once the full dwell has elapsed and we are
        # not in the middle of a field fade (i.e. we are at a clean field boundary).
        if self._timer >= self.dwell_seconds and self._field_transition == 0.0:
            self._advance_book(+1)
            return

        # Cycle through fields with a short fade.
        if num_fields > 1:
            fade_start = max(0.0, field_duration - self.FIELD_FADE_SECONDS)
            if self._field_timer >= fade_start and self._field_transition == 0.0:
                self._field_transition = 1.0
            if self._field_transition > 0.0:
                self._field_transition -= dt / self.FIELD_FADE_SECONDS
                if self._field_transition <= 0.0:
                    self._field_transition = 0.0
                    self._field_index = (self._field_index + 1) % num_fields
                    self._field_timer = 0.0
                    # If we just wrapped to the first field and the book's dwell
                    # time is up, advance to the next book instead of looping again.
                    if self._field_index == 0 and self._timer >= self.dwell_seconds:
                        self._advance_book(+1)
                        return

    def render(self, screen: pygame.Surface):
        screen.fill(self._bg)

        if self._error_message or not self.books:
            self._render_error(screen, self._error_message or "No books loaded")
            return

        cover_rect = self._get_cover_rect()
        panel_rect = self._get_panel_rect()

        # Draw cover shadow behind the cover area.
        shadow_rect = cover_rect.inflate(12, 12)
        pygame.draw.rect(screen, self._shadow, shadow_rect, border_radius=4)

        # Determine surfaces to render.
        cur_cover = self._current_cover
        next_cover = self._next_cover
        cur_fields = self._current_fields
        next_fields = self._next_fields

        # Book cross-fade takes precedence over field cross-fade.
        if self._book_transition > 0.0 and next_cover is not None:
            self._draw_surface_alpha(screen, next_cover, cover_rect, 1.0 - self._book_transition)
            self._draw_surface_alpha(screen, cur_cover, cover_rect, self._book_transition)

            cur_field = cur_fields[self._field_index] if cur_fields else None
            next_field = next_fields[0] if next_fields else None
            self._draw_surface_alpha(screen, next_field, panel_rect, 1.0 - self._book_transition)
            self._draw_surface_alpha(screen, cur_field, panel_rect, self._book_transition)
            return

        # Static or field-transition render.
        if cur_cover is not None:
            screen.blit(cur_cover, cover_rect)
            pygame.draw.rect(screen, self._accent, cover_rect, width=3, border_radius=2)

        if not cur_fields:
            return

        if self._field_transition > 0.0 and len(cur_fields) > 1:
            next_idx = (self._field_index + 1) % len(cur_fields)
            cur_field = cur_fields[self._field_index]
            next_field = cur_fields[next_idx]
            self._draw_surface_alpha(screen, next_field, panel_rect, 1.0 - self._field_transition)
            self._draw_surface_alpha(screen, cur_field, panel_rect, self._field_transition)
        else:
            field_surf = cur_fields[self._field_index]
            if field_surf is not None:
                screen.blit(field_surf, panel_rect.topleft)

    # ---------------- data loading ----------------

    def _load_books(self):
        """Load the JSON catalog.  On failure store an error message and empty list."""
        path = self._resolve_path(self.books_file)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.books = data.get("books", [])
            if not isinstance(self.books, list):
                raise ValueError("'books' must be a list")
            self._error_message = None
        except Exception as e:
            self.books = []
            self._error_message = f"Cannot load books:\n{path}\n{e}"
            print(f"[ImaginaryLibrary] {self._error_message}")

    def _scan_image_folder(self):
        """Build a sorted list of image files for index-based matching."""
        self._image_files = []
        folder = self._resolve_path(self.image_folder)
        if not os.path.isdir(folder):
            return
        files = []
        for name in os.listdir(folder):
            low = name.lower()
            if low.endswith(self.IMAGE_EXTS) and not name.startswith("."):
                files.append(name)
        self._image_files = sorted(files)

    def _resolve_path(self, path: str) -> str:
        """Return absolute path; if relative, resolve from the project root."""
        if os.path.isabs(path):
            return path
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, path)

    def _resolve_image_path(self, book: dict) -> str | None:
        """Return the filesystem path for a book's cover image, or None."""
        folder = self._resolve_path(self.image_folder)
        if not os.path.isdir(folder):
            return None

        if self.match_by == "index":
            idx = self.books.index(book)
            if idx < len(self._image_files):
                return os.path.join(folder, self._image_files[idx])
            return None

        # filename matching (default)
        filename = book.get("cover_image", "")
        if not filename:
            return None
        full = os.path.join(folder, filename)
        if os.path.isfile(full):
            return full
        return None

    # ---------------- book preparation ----------------

    def _prepare_book(self, index: int):
        """Load cover and render all field surfaces for the book at index."""
        if not self.books:
            return
        index = index % len(self.books)
        book = self.books[index]

        self._current_cover = self._load_cover(book)
        self._field_texts = self._collect_history_fields(book)
        self._current_fields = self._build_all_field_surfaces(book, self._field_texts)
        self._next_cover = None
        self._next_fields = []
        self._next_field_texts = []
        self._cached_book_index = index
        self._cached_size = (self.w, self.h)
        self._field_index = 0
        self._field_timer = 0.0
        self._field_transition = 0.0

    def _advance_book(self, delta: int):
        """Start a cross-fade to the next/previous book."""
        if not self.books or self._book_transition > 0.0 or self._field_transition > 0.0:
            return
        next_index = (self.book_index + delta) % len(self.books)
        book = self.books[next_index]

        self._next_cover = self._load_cover(book)
        self._next_field_texts = self._collect_history_fields(book)
        self._next_fields = self._build_all_field_surfaces(book, self._next_field_texts)
        self.book_index = next_index
        self._timer = 0.0
        self._book_transition = 1.0

    def _invalidate_cache(self):
        """Drop cached surfaces so they are rebuilt for the new resolution."""
        self._current_cover = None
        self._next_cover = None
        self._current_fields = []
        self._next_fields = []
        self._cached_book_index = -1
        self._cached_size = (0, 0)

    def _collect_history_fields(self, book: dict) -> list[str]:
        """Collect non-blank detailed_history_1..6 fields for a book."""
        fields = []
        for i in range(1, 7):
            text = book.get(f"detailed_history_{i}", "")
            if text and str(text).strip():
                fields.append(str(text).strip())
        # Backwards compatibility with the old single detailed_history field.
        if not fields and book.get("detailed_history"):
            text = str(book["detailed_history"]).strip()
            if text:
                fields.append(text)
        return fields

    def _build_all_field_surfaces(self, book: dict, history_fields: list[str]) -> list[pygame.Surface]:
        """Render one surface per history field, plus a metadata-only fallback."""
        total = max(len(history_fields), 1)
        if not history_fields:
            return [self._build_field_surface(book, None, 0, total)]
        return [self._build_field_surface(book, text, i, total) for i, text in enumerate(history_fields)]

    # ---------------- cover rendering ----------------

    def _load_cover(self, book: dict):
        """Return a cover surface, either loaded from disk or generated."""
        path = self._resolve_image_path(book)
        if path:
            try:
                img = self.manager.cache.get_image(path, convert_alpha=True)
                return self._fit_cover(img)
            except Exception as e:
                print(f"[ImaginaryLibrary] Failed to load cover '{path}': {e}")
        return self._build_placeholder_cover(book)

    def _fit_cover(self, img: pygame.Surface) -> pygame.Surface:
        """Scale an image to fit the cover rectangle while preserving aspect ratio."""
        rect = self._get_cover_rect()
        if rect.width <= 0 or rect.height <= 0:
            return img
        iw, ih = img.get_width(), img.get_height()
        scale = min(rect.width / max(1, iw), rect.height / max(1, ih))
        nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
        scaled = pygame.transform.smoothscale(img, (nw, nh))
        out = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        out.fill((0, 0, 0, 0))
        x = (rect.width - nw) // 2
        y = (rect.height - nh) // 2
        out.blit(scaled, (x, y))
        return out

    def _build_placeholder_cover(self, book: dict) -> pygame.Surface:
        """Generate a stylized fallback cover for missing images."""
        rect = self._get_cover_rect()
        w, h = max(1, rect.width), max(1, rect.height)

        # Derive a slightly varied color from the book id so each cover differs.
        seed = int(hashlib.sha1(book.get("id", "x").encode()).hexdigest(), 16)
        variation = (seed % 41) - 20
        base = self.placeholder_color
        color = tuple(max(0, min(255, c + variation)) for c in base)

        surf = pygame.Surface((w, h), pygame.SRCALPHA)
        surf.fill(color)

        # Decorative border.
        border = 8
        pygame.draw.rect(surf, self._accent, (border, border, w - 2 * border, h - 2 * border), 3)

        # Decorative corners.
        corner = 24
        line_w = 3
        for ox, oy in [(0, 0), (w - corner, 0), (0, h - corner), (w - corner, h - corner)]:
            pygame.draw.line(surf, self._accent, (ox + border, oy + border + corner // 2),
                             (ox + border + corner, oy + border + corner // 2), line_w)
            pygame.draw.line(surf, self._accent, (ox + border + corner // 2, oy + border),
                             (ox + border + corner // 2, oy + border + corner), line_w)

        title_font = self._get_font(self.title_font_size, bold=True)
        author_font = self._get_font(self.body_font_size, bold=False)
        small_font = self._get_font(self.small_font_size, bold=False)

        # Title, wrapped to fit.
        margin = max(24, w // 10)
        max_text_w = w - 2 * margin
        title_lines = self._wrap_lines(title_font, book.get("title", "?"), max_text_w)
        y = h // 4
        for line in title_lines:
            ts = title_font.render(line, True, self._title)
            surf.blit(ts, ((w - ts.get_width()) // 2, y))
            y += ts.get_height() + 6

        # Author.
        author = book.get("author", "")
        if author:
            asurf = author_font.render(author, True, self._subtitle)
            surf.blit(asurf, ((w - asurf.get_width()) // 2, y + 12))

        # Genre / year at bottom.
        footer = f"{book.get('year', '')}  •  {book.get('genre', '')}"
        fsurf = small_font.render(footer, True, self._dim)
        surf.blit(fsurf, ((w - fsurf.get_width()) // 2, h - margin - fsurf.get_height()))

        return surf

    # ---------------- text rendering ----------------

    def _build_field_surface(self, book: dict, history_text: str | None,
                             field_index: int = 0, total_fields: int = 1) -> pygame.Surface:
        """Render one right-panel view: metadata plus a single history segment."""
        panel = self._get_panel_rect()
        width = max(1, panel.width)
        height = max(1, panel.height)
        margin = max(12, width // 25)
        inner_w = width - 2 * margin

        title_font = self._get_font(self.title_font_size, bold=True)
        section_font_size = max(8, int(self.body_font_size * 0.75))
        section_font = self._get_font(section_font_size, bold=False, italic=False)
        section_bold = self._get_font(section_font_size, bold=True, italic=False)
        small_font = self._get_font(self.small_font_size, bold=False, italic=False)
        small_italic = self._get_font(self.small_font_size, bold=False, italic=True)
        tag_font = self._get_font(self.tag_font_size, bold=False, italic=False)

        sections = []

        # Title
        title_lines = self._wrap_lines(title_font, book.get("title", "?"), inner_w)
        sections.append(("lines", title_lines, title_font, self._title, 0))

        # Author / year / publisher
        author_text = book.get("author", "")
        year = book.get("year")
        publisher = book.get("publisher", "")
        if author_text and year:
            author_text = f"{author_text}, {year}"
        if publisher:
            author_text = f"{author_text}\n{publisher}" if author_text else publisher
        if author_text:
            sections.append(("para", author_text, small_italic, self._subtitle, 8))

        # Language / genre / pages
        meta_parts = []
        if book.get("language"):
            meta_parts.append(str(book["language"]))
        if book.get("genre"):
            meta_parts.append(str(book["genre"]))
        if book.get("pages"):
            meta_parts.append(f"{book['pages']} pp.")
        if meta_parts:
            sections.append(("line", "  •  ".join(meta_parts), small_font, self._dim, 12))

        # Review excerpt
        if self.show_review and book.get("review_excerpt"):
            sections.append(("para", f"“{book['review_excerpt']}”", small_italic, self._accent, 16))

        # Publication history
        if book.get("publication_history"):
            sections.append(("label", "Publication History", section_bold, self._body, 20))
            sections.append(("para", book["publication_history"], section_font, self._body, 6))

        # Synopsis
        if book.get("synopsis"):
            sections.append(("label", "Synopsis", section_bold, self._body, 20))
            sections.append(("para", book["synopsis"], section_font, self._body, 6))

        # One detailed-history segment
        if history_text:
            label = f"History ({field_index + 1} of {total_fields})"
            sections.append(("label", label, section_bold, self._body, 20))
            sections.append(("para", history_text, section_font, self._body, 6))

        # Tags
        if self.show_tags and book.get("tags"):
            sections.append(("tags", book["tags"], tag_font, self._tag_fg, 20))

        surf = pygame.Surface((width, height), pygame.SRCALPHA)
        surf.fill((0, 0, 0, 0))

        y = margin
        for kind, payload, font, color, gap in sections:
            y += gap
            line_h = font.get_height() + 4
            if kind == "lines":
                for line in payload:
                    if y + font.get_height() > height - margin:
                        break
                    ls = font.render(line, True, color)
                    surf.blit(ls, (margin, y))
                    y += ls.get_height() + 4
            elif kind == "line":
                if y + font.get_height() > height - margin:
                    break
                ls = font.render(payload, True, color)
                surf.blit(ls, (margin, y))
                y += ls.get_height() + 4
            elif kind == "para":
                for raw in payload.splitlines():
                    wrapped = self._wrap_lines(font, raw, inner_w)
                    for line in wrapped:
                        if y + font.get_height() > height - margin:
                            break
                        ls = font.render(line, True, color)
                        surf.blit(ls, (margin, y))
                        y += ls.get_height() + 4
                    y += 6
            elif kind == "label":
                if y + font.get_height() > height - margin:
                    break
                ls = font.render(payload, True, color)
                surf.blit(ls, (margin, y))
                y += ls.get_height() + 4
            elif kind == "tags":
                tag_h = font.get_height() + 8
                x = margin
                for tag in payload:
                    ts = font.render(tag, True, color)
                    tag_w = ts.get_width() + 16
                    if x + tag_w > width - margin:
                        x = margin
                        y += tag_h + 6
                    if y + tag_h > height - margin:
                        break
                    pill_rect = pygame.Rect(x, y, tag_w, tag_h)
                    pygame.draw.rect(surf, self._tag_bg, pill_rect, border_radius=4)
                    surf.blit(ts, (x + 8, y + 4))
                    x += tag_w + 8
                y += tag_h

        return surf

    # ---------------- layout helpers ----------------

    def _get_cover_rect(self) -> pygame.Rect:
        """Compute the rectangle for the book cover."""
        padding = max(24, int(self.w * 0.025))
        aspect = 800 / 1200

        if self.portrait_layout:
            cover_area_h = int(self.h * 0.45)
            available_w = self.w - 2 * padding
            available_h = cover_area_h - 2 * padding
            cw = min(available_w, int(available_h * aspect))
            ch = min(available_h, int(available_w / aspect))
            x = padding + (self.w - cw) // 2
            y = padding + (cover_area_h - ch) // 2
            return pygame.Rect(x, y, cw, ch)

        cover_area_w = int(self.w * 0.35)
        available_w = cover_area_w - 2 * padding
        available_h = self.h - 2 * padding
        cw = min(available_w, int(available_h * aspect))
        ch = min(available_h, int(available_w / aspect))
        x = padding + (cover_area_w - cw) // 2
        y = padding + (self.h - 2 * padding - ch) // 2
        return pygame.Rect(x, y, cw, ch)

    def _get_panel_rect(self) -> pygame.Rect:
        """Compute the rectangle for the text panel."""
        padding = max(24, int(self.w * 0.025))

        if self.portrait_layout:
            cover_rect = self._get_cover_rect()
            x = padding
            y = cover_rect.bottom + padding
            w = max(1, self.w - 2 * padding)
            h = max(1, self.h - y - padding)
            rect = pygame.Rect(x, y, w, h)
            self._panel_rect = rect
            return rect

        cover_x = self._get_cover_rect().right
        x = cover_x + padding
        y = padding
        w = max(1, self.w - x - padding)
        h = max(1, self.h - 2 * padding)
        rect = pygame.Rect(x, y, w, h)
        self._panel_rect = rect
        return rect

    # ---------------- font / text utilities ----------------

    def _get_font(self, size: int, bold: bool = False, italic: bool = False) -> pygame.font.Font:
        """Return a cached font, supporting either a system font name or a font file path."""
        key = (self.font_name, size, bold, italic)
        f = self._font_cache.get(key)
        if f is not None:
            return f

        name = self.font_name
        try:
            if name and os.path.isfile(name):
                # File-based fonts are loaded fresh each time so bold/italic
                # styling never leaks through the shared manager cache.
                f = pygame.font.Font(name, size)
                f.set_bold(bold)
                f.set_italic(italic)
            else:
                # Build a system font with the exact style flags instead of
                # reusing the manager's shared cache, which does not key on
                # italic and would otherwise mutate other references.
                f = pygame.font.SysFont(name if name else None, size, bold=bold, italic=italic)
        except Exception as e:
            print(f"[ImaginaryLibrary] Font load failed ({name}, {size}px): {e}; falling back")
            f = pygame.font.Font(None, size)
            f.set_bold(bold)
            f.set_italic(italic)

        self._font_cache[key] = f
        return f

    def _wrap_lines(self, font: pygame.font.Font, text: str, max_width: int) -> list[str]:
        """Wrap text into lines that fit within max_width using the given font."""
        text = text or ""
        words = text.split()
        if not words:
            return []
        lines, cur = [], ""
        for word in words:
            test = word if not cur else cur + " " + word
            if font.size(test)[0] <= max_width:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    def _draw_surface_alpha(self, screen: pygame.Surface, surf: pygame.Surface | None,
                            rect: pygame.Rect, alpha: float):
        """Blit a surface with an overall alpha multiplier."""
        if surf is None or alpha <= 0.0:
            return
        if alpha >= 1.0:
            screen.blit(surf, rect)
            return
        temp = surf.copy()
        temp.set_alpha(int(255 * alpha))
        screen.blit(temp, rect)

    def _render_error(self, screen: pygame.Surface, message: str):
        """Render a friendly error screen when the catalog cannot load."""
        screen.fill(self._bg)
        try:
            font = self._get_font(self.body_font_size, bold=False)
        except Exception:
            font = pygame.font.Font(None, self.body_font_size)
        lines = message.splitlines()
        y = self.h // 4
        for line in lines:
            surf = font.render(line, True, self._body)
            x = (self.w - surf.get_width()) // 2
            screen.blit(surf, (x, y))
            y += surf.get_height() + 8
