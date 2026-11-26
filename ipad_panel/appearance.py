from colorsys import hls_to_rgb

PALETTES = {
    'sage': ('Sage', 92, 32, '#a5ba7b'),
    'graphite': ('Graphite', 218, 9, '#8e9bae'),
    'ocean': ('Ocean', 208, 52, '#659cd1'),
    'teal': ('Teal', 173, 43, '#52aa9d'),
    'indigo': ('Indigo', 235, 49, '#8b92dc'),
    'lavender': ('Lavender', 272, 35, '#b694cc'),
    'amber': ('Amber', 40, 64, '#d3a051'),
    'terracotta': ('Terracotta', 15, 49, '#cd8874'),
}
DEFAULT_PALETTE = 'sage'


def palette_id(value):
    if not isinstance(value, str) or value not in PALETTES:
        raise ValueError('Choose one of the available panel palettes.')
    return value


def color(hue, saturation, lightness):
    rgb = hls_to_rgb(hue / 360, lightness / 100, saturation / 100)
    return '#' + ''.join(f'{round(channel * 255):02x}' for channel in rgb)


def stylesheet():
    # Generate plain color declarations instead of depending on CSS variables in old Safari.
    rules = []
    for key, (_, hue, saturation, _) in PALETTES.items():
        if key == DEFAULT_PALETTE:  # Keep the original colors and contrast on upgrade.
            continue
        for theme in ('dark', 'light'):
            dark = theme == 'dark'
            prefix = f'[data-theme={theme}][data-palette={key}]'
            c = lambda lightness, tone=1: color(hue, saturation * tone, lightness)
            bg, surface, tint = (c(10, .42), c(15, .47), c(19, .55)) if dark else (c(95, .45), c(99, .45), c(92, .55))
            accent, accent_text = (c(80), '#141a20') if dark else (c(29), '#ffffff')
            border, input_border = (c(37, .62), c(51, .58)) if dark else (c(72, .52), c(47, .55))
            text = c(95, .45) if dark else c(15, .52)
            soft = c(77, .45) if dark else c(36, .53)
            active_bg, active_text = (c(23, .8), c(97)) if dark else (c(89, .75), c(19))
            groups = {
                'body': f'background:{bg};color:{text}',
                '.tile, .weather': f'background:{surface};color:{text};border-color:{border}',
                '.appearance, .inspector, .catalogue, .board, .empty, .climate-options, .console-targets': f'background:{tint};border-color:{border}',
                'button, .button, select, input, .climate-disclosure summary, .palette-choice': f'background:{tint};border-color:{input_border}',
                '.tile-label, .hint, #date, .tile-unit, .results small, .climate-caption': f'color:{soft}',
                '.update:not(.warning)': f'color:{soft}',
                '.update time': f'color:{text}',
                'a, .eyebrow, .weather > span, .feedback:not(.error)': f'color:{accent}',
                ':focus, .control:active': f'outline-color:{accent}',
                'button.primary, button[aria-pressed=true]:not(.control)': f'background:{accent};border-color:{accent};color:{accent_text}',
                '.control.is-on': f'background:{active_bg};border-color:{input_border};color:{active_text}',
                '.control.is-on .tile-label, .control.is-on .power': f'color:{active_text}',
                '.glyph, .cell.empty-cell': f'background:{tint};color:{soft}',
                '.cell.selected': f'background:{active_bg};border-color:{accent};color:{active_text}',
                '.board .drag-target': f'border-color:{accent};outline-color:{accent}',
            }
            for selectors, declarations in groups.items():
                rules.append(','.join(f'{prefix} {selector.strip()}' for selector in selectors.split(',')) + '{' + declarations + '}')
    return '\n'.join(rules)
