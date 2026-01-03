from .models import Config, db
import json
import re

def get_conf(key, default):
    c = Config.query.filter_by(key=key).first()
    return json.loads(c.value) if c else default

def set_conf(key, value):
    c = Config.query.filter_by(key=key).first()
    if not c:
        db.session.add(Config(key=key, value=json.dumps(value, ensure_ascii=False)))
    else:
        c.value = json.dumps(value, ensure_ascii=False)
    db.session.commit()

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
    
    def replace_tag(match):
        is_closing = match.group(1)  # '/' if closing tag, '' if opening
        tag_name = match.group(2).lower()
        attributes = match.group(3)  # Everything between tag name and >
        
        # Special handling for <a> tags - keep href attribute
        if tag_name == 'a' and not is_closing:
            # Extract href attribute if present
            href_match = re.search(r'href\s*=\s*["\']([^"\']*)["\']', attributes, re.IGNORECASE)
            if href_match:
                href_value = href_match.group(1)
                # Escape any quotes in href
                href_value = href_value.replace('"', '&quot;')
                return f'<a href="{href_value}">'
            else:
                # <a> without href is invalid, remove it
                return ''
        
        # Special handling for <span> tags - only allow with class="tg-spoiler"
        if tag_name == 'span':
            if not is_closing:
                # Check if it has class="tg-spoiler"
                if 'class' in attributes and 'tg-spoiler' in attributes:
                    return '<span class="tg-spoiler">'
                else:
                    # Invalid span tag, remove but keep content
                    return ''
            else:
                # For closing span, check if the opening was valid
                # Since we can't track state easily, we'll just remove it
                return ''
        
        # For allowed tags, return them without attributes
        if tag_name in allowed_tags:
            return f'<{is_closing}{tag_name}>'
        
        # For disallowed tags, remove them but keep their content
        return ''
    
    # Replace all HTML tags according to rules
    sanitized = re.sub(tag_pattern, replace_tag, text)
    
    return sanitized
