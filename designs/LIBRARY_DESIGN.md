# Imaginary Library Mode — Design Document

Status: **DRAFT FOR REVIEW**  
Mode type key: `imaginarylibrary`  
Source file: `modes/imaginary_library_mode.py`  
Data file: `data/imaginary_library/books.json`  

---

## 1. Goal

A self-contained kiosk mode that presents one forbidden medieval manuscript at a time. Every book is a tome of dangerous knowledge in the tradition of H. P. Lovecraft: strange Latin, German, Greek, Arabic, Hebrew, Syriac, and Coptic titles; monastic authors who came to bad ends; suppressed editions; and a pervasive sense that the book should not be opened. All text is generated offline and stored in JSON; no network calls occur at runtime. The user supplies a folder of 800×1200 cover images, and the mode matches each image to an entry in `books.json`.

## 2. How it works (offline-first)

1. At build time:
   - Generate 25 seed entries with title, author, year, publisher, language, pages, genre, publication history, synopsis, review excerpt, and tags.
   - Titles are in Latin, Middle High German, Greek, Arabic, Syriac, Hebrew, Coptic, and Old Norse.
   - Store them in `data/imaginary_library/books.json` with six empty `detailed_history_1` through `detailed_history_6` fields.
2. User enrichment step:
   - The user feeds each `synopsis` (and title/author/year) to an LLM using the generic prompt below.
   - The generated response is split into six short segments and copied into `detailed_history_1` through `detailed_history_6`.
3. At runtime:
   - The mode loads `books.json` and the configured image folder.
   - It displays one book for `dwell_seconds` (default 180), cycling through the six history segments on the right panel.
   - Blank segments are skipped. Segments fade from one to the next and loop until the book timer expires.
   - No API calls, no secrets, no background threads required.

## 3. Generic LLM prompt for detailed histories

Use this prompt for each book, replacing the bracketed placeholders:

```
Write six short fictional-history segments for a forbidden medieval manuscript titled "[TITLE]"
by [AUTHOR], originally produced around the year [YEAR]. The book is a tome of dangerous,
Lovecraftian knowledge. Base the history on this synopsis: [SYNOPSIS]

Each segment should be one or two paragraphs and together cover the following elements:
1. The manuscript's origins: where and by whom it was written, and what the author claimed to have learned.
2. A physical description of the book: materials, binding, illuminations, stains, damage, or unusual features.
3. Why it was considered dangerous or heretical, and which authorities tried to suppress it.
4. Notable owners, incidents, or disasters connected to the manuscript.
5. Attempts to destroy, copy, translate, or study it, and what happened to those who tried.
6. Its current rumored location or status.

Number the segments 1 through 6. Write in an academic but ominous tone, as if for a restricted museum catalog or an occult bibliography. Do not break character by acknowledging that the book is fictional.
```

Example filled prompt (for lib_001):

```
Write six short fictional-history segments for a forbidden medieval manuscript titled "Codex Tenebrarum"
by Brother Aldric of the Black Cloister, originally produced around the year 1187. The book is a tome of dangerous,
Lovecraftian knowledge. Base the history on this synopsis: A monastic catalog of shadows that have detached themselves from their owners and begun to live independent lives in the corners of cathedrals.

Each segment should be one or two paragraphs and together cover the following elements:
1. The manuscript's origins: where and by whom it was written, and what the author claimed to have learned.
2. A physical description of the book: materials, binding, illuminations, stains, damage, or unusual features.
3. Why it was considered dangerous or heretical, and which authorities tried to suppress it.
4. Notable owners, incidents, or disasters connected to the manuscript.
5. Attempts to destroy, copy, translate, or study it, and what happened to those who tried.
6. Its current rumored location or status.

Number the segments 1 through 6. Write in an academic but ominous tone, as if for a restricted museum catalog or an occult bibliography. Do not break character by acknowledging that the book is fictional.
```

## 4. JSON schema

File: `data/imaginary_library/books.json`

```json
{
  "books": [
    {
      "id": "lib_001",
      "title": "Codex Tenebrarum",
      "author": "Brother Aldric of the Black Cloister",
      "year": 1187,
      "publisher": "Copied by candlelight at St. Vitus-in-the-Dark, Bohemia",
      "language": "Latin",
      "pages": 144,
      "genre": "Forbidden Grimoire",
      "cover_image": "001.jpg",
      "publication_history": "Only three copies are known...",
      "synopsis": "A monastic catalog of shadows...",
      "detailed_history_1": "",
      "detailed_history_2": "",
      "detailed_history_3": "",
      "detailed_history_4": "",
      "detailed_history_5": "",
      "detailed_history_6": "",
      "review_excerpt": "The shadows in my chamber moved differently after I closed it...",
      "tags": ["grimoire", "shadows", "monastic", "forbidden"]
    }
  ]
}
```

### Field definitions

| Field | Required | Description |
|-------|----------|-------------|
| `id` | yes | Stable identifier (`lib_001` – `lib_025`) |
| `title` | yes | Book title, often in Latin/Greek/German/etc. |
| `author` | yes | Author or attributed author |
| `year` | yes | Original production year |
| `publisher` | yes | Scriptorium, press, or place of origin |
| `language` | yes | Original language |
| `pages` | yes | Page count |
| `genre` | yes | Genre label |
| `cover_image` | yes | Filename expected in the image folder (e.g. `001.jpg`) |
| `publication_history` | yes | Brief history of suppression, survival, and ownership |
| `synopsis` | yes | Brief summary of the forbidden content; used as LLM prompt seed |
| `detailed_history_1` .. `detailed_history_6` | no | Six short history segments; blank segments are skipped |
| `review_excerpt` | yes | One-line ominous review quote |
| `tags` | yes | Array of tag strings |

## 5. Generated seed catalog (25 forbidden manuscripts)

| ID | Title | Author | Year | Language |
|----|-------|--------|------|----------|
| lib_001 | Codex Tenebrarum | Brother Aldric of the Black Cloister | 1187 | Latin |
| lib_002 | Das Buch der letzten Atemzüge | Hildebrandt der Stille | 1362 | Middle High German |
| lib_003 | Liber Mundi Invisibilis | Al-Kindi's unknown pupil | 892 | Arabic with Latin glosses |
| lib_004 | Malleus Deorum Silentium | Sister Praetextata of Aquileia | 1044 | Latin |
| lib_005 | Chronicon Subterraneum | Thorkell the Worm-Tongued | 1123 | Old Norse |
| lib_006 | Vermis Mysteriorum | Caius Sempronius the Pale | 64 | Latin |
| lib_007 | Septem Sigilla Profundi | The Seven Anonymous Anchorites | 1307 | Latin |
| lib_008 | Das Grauen aus den Kellern | Konrad von Nürnberg | 1472 | Early New High German |
| lib_009 | Liber Ossium Sonantium | Ostanes the Chaldean, attributed | 410 | Greek with Chaldean invocations |
| lib_010 | Fragmenta Antiquissima | Unknown; possibly pre-Phoenician | 800 | Unknown script with Latin translation |
| lib_011 | Grimoire des Verborgenen Königs | Eberhard der Schattenleser | 1399 | Middle High German |
| lib_012 | Tractatus de Portis Insomnium | Master Roger of Hereford | 1228 | Latin |
| lib_013 | Codex Lunae Mortuae | Arnaud de Montfaucon | 1455 | Latin |
| lib_014 | Liber Facierum Absconditarum | Ibn al-Haytham's apostate student | 1011 | Arabic |
| lib_015 | Die Stimmen unter dem Boden | Anna von der Tiefe | 1533 | Early New High German |
| lib_016 | Mysterium Arcae Noctis | Brother Theodosius the Sleepless | 884 | Greek |
| lib_017 | Vocabularium Tenebrarum | Ephraim the Lexicographer | 1176 | Syriac with Latin interlinear |
| lib_018 | Chronica Eorum qui Descenderunt | Decius Mus, chronicler of the Templars | 1291 | Latin |
| lib_019 | Liber Aquarum Oblitarum | Hypatia's unnamed copyist | 415 | Greek |
| lib_020 | Das Auge das nie schließt | Friedrich von Aue | 1410 | Middle High German |
| lib_021 | Liber Sanguinis Subterranei | Maria de la Sangre Oculta | 1492 | Latin |
| lib_022 | Codex Finis Mundi | The Last Librarian of Alexandria, attributed | 500 | Coptic with Greek annotations |
| lib_023 | Das Buch ohne Anfang | Unknown; first words are the middle of a sentence | 1337 | Middle High German |
| lib_024 | Testamentum Vaccae Stellarum | Baal-Hanan the Stargazer | 720 | Hebrew with Aramaic glosses |
| lib_025 | De Cultu Serpentium Sapientium | Bishop Serapion the Unclean | 610 | Greek |

The full text for all fields is in `data/imaginary_library/books.json`.

## 6. Image handling

- User provides a folder of 800×1200 cover images.
- Config key: `image_folder` (absolute or relative path).
- Matching strategy (configurable):
  - **filename** (default): `cover_image` field in JSON must match a file in the folder.
  - **index**: sort image files alphabetically and assign them to books in order.
- Missing image fallback: render a generated placeholder cover using the book's dominant color (derived from `id` hash), title, and author.
- Image caching: load via `manager.cache` so the mode releases it cleanly in `exit()`.

## 7. Config schema

Registry entry in `modes_registry.json`:

```json
"imaginarylibrary": {
  "entrypoint": "modes.imaginary_library_mode:ImaginaryLibraryMode",
  "type_config": {
    "dwell_seconds": 180,
    "image_folder": "assets/imaginary_library",
    "match_by": "filename",
    "placeholder_color": [40, 35, 55],
    "show_tags": true,
    "show_review": true
  },
  "required": ["image_folder"],
  "optional": [
    "books_file",
    "dwell_seconds",
    "match_by",
    "placeholder_color",
    "show_tags",
    "show_review",
    "font_name",
    "title_font_size",
    "body_font_size",
    "small_font_size",
    "tag_font_size"
  ]
}
```

Instance entry in `modes_config.json`:

```json
"33": {
  "type": "imaginarylibrary",
  "image_folder": "assets/imaginary_library",
  "dwell_seconds": 180
}
```

### Config parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `image_folder` | required | Folder containing 800×1200 book-cover images |
| `dwell_seconds` | `180` | Seconds each book is displayed (three minutes) |
| `match_by` | `"filename"` | `"filename"` uses `cover_image`; `"index"` uses alphabetical order |
| `placeholder_color` | `[40, 35, 55]` | RGB base color for missing-cover fallback |
| `show_tags` | `true` | Render tag pills below the synopsis |
| `show_review` | `true` | Render the review excerpt |
| `font_name` | `null` | Optional path to a TTF; falls back to default pygame font |
| `title_font_size` | `48` | Title text size |
| `body_font_size` | `48` | Body text size |
| `small_font_size` | `36` | Author, publisher, meta, review text size |
| `tag_font_size` | `32` | Tag pill text size |

## 8. Display layout

For a typical landscape kiosk screen:

- **Left third**: book cover image, centered, scaled to fit a fixed rectangle (e.g. 480×720), with a subtle drop shadow.
- **Right two-thirds**: stacked text blocks with consistent padding:
  1. Title (large, bold)
  2. Author + year + publisher (smaller, italic)
  3. Language + genre + pages (one line)
  4. Review excerpt (quoted, slightly dim color)
  5. Publication history (body text)
  6. Synopsis (body text)
  7. Tags (small pills)
  8. One `detailed_history_N` segment (labelled "History")

The right panel repeats the same metadata every time; only the "History" segment changes. The six segments are shown in order, with a short fade between each. Blank segments are skipped. The segments loop until `dwell_seconds` expires, then the mode cross-fades to the next book.

Each segment should fit on a single screen; overflow is clipped so that long text encourages splitting into smaller segments.

## 9. Class outline

```python
class ImaginaryLibraryMode:
    def __init__(self, config: dict): ...
    def enter(self, manager): ...
    def exit(self): ...
    def handle_event(self, event): ...
    def update(self, dt): ...
    def render(self, screen): ...
```

### Responsibilities

- `__init__`: store config, set defaults.
- `enter`: load `books.json`, scan `image_folder`, build text surfaces, start timer.
- `exit`: release surfaces and image references.
- `handle_event`: LEFT/RIGHT advance to previous/next book in single-mode tests.
- `update`: advance book timer; cycle through history fields with short fades.
- `render`: draw cover + metadata panel (current field, or cross-fading fields/books).

## 10. Transitions

- Use `core/manager.py` fade in/out for the whole mode.
- Internal book change: cross-fade alpha over ~0.8 seconds or a gentle slide.
- Keep transition logic minimal to avoid per-frame surface churn.

## 11. Error handling

- If `books.json` is missing or malformed: log once, render a single fallback screen explaining the error, and idle.
- If an image is missing: render the generated placeholder and continue.
- If `image_folder` is missing: render text covers for all books and log a warning.

## 12. Testing plan

1. Validate config: `python validate_configs.py --all`
2. Run windowed: `python pixel_drift.py --play 33 --windowed`
3. Verify with missing images (placeholder covers appear).
4. Verify with filled `detailed_history_1` through `detailed_history_6` (segments fade from one to the next; blank segments are skipped).
5. Verify `exit()` releases surfaces (no lingering references).

## 13. Next steps

1. Review this design and the generated catalog in `data/imaginary_library/books.json`.
2. Confirm the image folder path and naming convention for your 800×1200 covers.
3. Optionally fill `detailed_history_1` through `detailed_history_6` for each book using the generic prompt in section 3.
4. Green-light the design so implementation can begin.

---

End of design document.
