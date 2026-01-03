from . import db
import json
import re

def sanitize_html_for_telegram(text):
    """
    Sanitize HTML to only include Telegram-supported tags.
    
    Telegram supports these HTML tags:
    - <b>, <strong> - bold
    - <i>, <em> - italic
    - <u>, <ins> - underline
    - <s>, <strike>, <del> - strikethrough
    - <code> - inline code
    - <pre> - code block
    - <a href=""> - link
    - <tg-spoiler> or <span class="tg-spoiler"> - spoiler
    - <tg-emoji> - custom emoji
    
    All other tags will be removed while preserving their content.
    """
    if not text:
        return text
    
    # List of allowed tags (without attributes, except special cases)
    allowed_tags = {
        'b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del',
        'code', 'pre', 'tg-spoiler', 'tg-emoji'
    }
    
    # Pattern to match HTML tags
    # This will match opening tags, closing tags, and self-closing tags
    tag_pattern = r'<(/?)([a-zA-Z][\w-]*)((?:\s+[^>]*)?)>'
    
    # Track which special tags (a, span) have valid openings
    # We need to track opening tags to know if closing tags are valid
    valid_openings = []
    result_parts = []
    last_end = 0
    
    for match in re.finditer(tag_pattern, text):
        # Add text before this tag
        result_parts.append(text[last_end:match.start()])
        last_end = match.end()
        
        is_closing = match.group(1)  # '/' if closing tag, '' if opening
        tag_name = match.group(2).lower()
        attributes = match.group(3)  # Everything between tag name and >
        
        # Special handling for <a> tags - keep href attribute
        if tag_name == 'a':
            if not is_closing:
                # Extract href attribute if present
                href_match = re.search(r'href\s*=\s*["\']([^"\']*)["\']', attributes, re.IGNORECASE)
                if href_match:
                    href_value = href_match.group(1)
                    # Escape any quotes in href
                    href_value = href_value.replace('"', '&quot;')
                    result_parts.append(f'<a href="{href_value}">')
                    valid_openings.append('a')
                else:
                    # <a> without href is invalid, remove it
                    pass
            else:
                # Closing </a> tag - only keep if we have a valid opening
                if valid_openings and valid_openings[-1] == 'a':
                    result_parts.append('</a>')
                    valid_openings.pop()
            continue
        
        # Special handling for <span> tags - only allow with class="tg-spoiler"
        if tag_name == 'span':
            if not is_closing:
                # Check if it has class="tg-spoiler"
                # Use proper regex to extract class attribute value
                class_match = re.search(r'class\s*=\s*["\']([^"\']*)["\']', attributes, re.IGNORECASE)
                if class_match and 'tg-spoiler' == class_match.group(1).strip():
                    result_parts.append('<span class="tg-spoiler">')
                    valid_openings.append('span')
                else:
                    # Invalid span tag, remove but keep content
                    pass
            else:
                # Closing </span> tag - only keep if we have a valid opening
                if valid_openings and valid_openings[-1] == 'span':
                    result_parts.append('</span>')
                    valid_openings.pop()
            continue
        
        # For allowed tags, return them without attributes
        if tag_name in allowed_tags:
            result_parts.append(f'<{is_closing}{tag_name}>')
            continue
        
        # For disallowed tags, remove them but keep their content
        # (do nothing, just skip the tag)
    
    # Add remaining text after last tag
    result_parts.append(text[last_end:])
    
    return ''.join(result_parts)
