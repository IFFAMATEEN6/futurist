"""Local SVG icons; no external fonts, images or icon network requests."""
PATHS = {
    "brand": '<path d="M5 5h16v6H11v5h8v6h-8v7H5z" fill="currentColor" stroke="none"/><path d="M22 16h7v13h-7z" fill="currentColor" stroke="none"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/>',
    "person": '<circle cx="12" cy="8" r="4"/><path d="M4 21v-2a8 8 0 0 1 16 0v2"/>',
    "shield": '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/>',
    "match": '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="var(--icon-fill,white)"/><circle cx="15" cy="17" r="3" fill="var(--icon-fill,white)"/>',
    "calendar": '<rect x="3" y="5" width="18" height="16" rx="3"/><path d="M7 3v4m10-4v4M3 11h18m-13 5 3 3 5-5"/>',
    "arrow": '<path d="M4 12h16m-6-6 6 6-6 6"/>',
    "external": '<path d="M14 4h6v6m0-6L10 14M10 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4"/>',
    "briefcase": '<rect x="3" y="7" width="18" height="14" rx="3"/><path d="M8 7V4h8v3M3 12a20 20 0 0 0 18 0m-9 0v4"/>',
    "book": '<path d="M12 6C9 3 5 3 2 4v15c4-1 7 0 10 2 3-2 6-3 10-2V4c-4-1-7 0-10 2Zm0 0v15"/>',
    "chat": '<path d="M21 11a8 8 0 0 1-8 8H8l-5 3v-7a9 9 0 1 1 18-4Z"/><path d="M7 9h10M7 13h6"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
    "layers": '<path d="m12 3 10 5-10 5L2 8Zm-9 10 9 5 9-5M3 18l9 5 9-5"/>',
    "check": '<path d="m5 12 4 4L20 5"/>',
    "document": '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M8 13h8M8 17h6"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.01"/>',
    "flag": '<path d="M5 21V4c5-4 9 4 15 0v11c-6 4-10-4-15 0"/>',
}


def icon(name, size=24):
    box = "0 0 34 34" if name == "brand" else "0 0 24 24"
    return (f'<svg width="{size}" height="{size}" viewBox="{box}" fill="none" stroke="currentColor" '
            f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            + PATHS.get(name, PATHS["document"]) + "</svg>")
