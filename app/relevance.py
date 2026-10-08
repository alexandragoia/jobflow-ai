"""Conservative lexical matching. A match is evidence, never a suitability claim."""
import html
import re


def clean_keyword(value):
    value = value.replace('\\*', '*').strip()
    value = re.sub(r'^[\s*•\-–—]+|[\s*]+$', '', value)
    value = re.sub(r'^\d+[.)]\s+', '', value)
    return re.sub(r'\s+', ' ', re.sub(r'(?:\.{3}|…)\s*$', '', value)).strip()


def normalized(value):
    value = html.unescape(value or '').casefold()
    for original, replacement in [('ä', 'ae'), ('ö', 'oe'), ('ü', 'ue'), ('ß', 'ss')]:
        value = value.replace(original, replacement)
    return ' '.join(re.findall(r'\w+', value))


# Alternatives are intentionally narrow: they describe the same role, not an industry.
ALIASES = {
    'buero hilfe': ['buero hilfe'],
    'buerohilfe': ['buerohilfe', 'buerohelfer', 'buerohelferin'],
    'buerokraft': ['buerokraft', 'buerokraefte'],
    'teamassistenz': ['teamassistenz', 'teamassistent', 'teamassistentin'],
    'pflegehelfer': ['pflegehelfer', 'pflegehelferin', 'pflegehilfe'],
    'haushaltshilfe': ['haushaltshilfe', 'haushaltshilfen'],
    'hauswirtschaftsleitung': ['hauswirtschaftsleitung', 'hauswirtschaftsleiter', 'hauswirtschaftsleiterin'],
    'betreuungsassistent': ['betreuungsassistent', 'betreuungsassistentin'],
    'schulbegleiter': ['schulbegleiter', 'schulbegleiterin', 'schulbegleitung'],
    'alltagsbegleiter': ['alltagsbegleiter', 'alltagsbegleiterin', 'alltagsbegleitung'],
    'sozialassistent': ['sozialassistent', 'sozialassistentin'],
    'integrationshelfer': ['integrationshelfer', 'integrationshelferin', 'integrationshilfe'],
    'jobcoach': ['jobcoach', 'job coach'],
    'sprachmittler': ['sprachmittler', 'sprachmittlerin', 'sprachmittlung'],
    'rumaenisch': ['rumaenisch', 'rumaenischer', 'rumaenische', 'rumaenischen', 'romanian'],
    'spanisch': ['spanisch', 'spanischer', 'spanische', 'spanischen', 'spanish'],
    'ki': ['ki', 'ai', 'kuenstliche intelligenz', 'artificial intelligence'],
    'automatisierung': ['automatisierung', 'automatisierungen', 'automation', 'automatisierungsprozesse'],
    'persoenliche assistenz': ['persoenliche assistenz', 'persoenlichen assistenz'],
    'leitung': ['teamleiter', 'teamleiterin', 'teamleitung', 'supervisor', 'leitung', 'hausdame'],
}


def contains(text, alternatives):
    return any(re.search(r'(?<!\w)' + re.escape(term).replace(r'\ ', r'\s+') + r'(?!\w)', text)
               for term in alternatives)


def groups(keyword):
    value = normalized(keyword)
    # Career-change wording cannot identify a job on its own.
    value = re.sub(r'\bquereinsteiger(?:in)?\b', '', value).strip()
    if not value:
        return [['quereinsteiger', 'quereinsteigerin']]
    if value in ('housekeeping supervisor', 'teamleiter housekeeping'):
        return [['housekeeping'], ALIASES['leitung']]
    if value in ALIASES:
        return [ALIASES[value]]
    result = []
    for word in value.split():
        if word.startswith('rumaenisch'):
            word = 'rumaenisch'
        elif word.startswith('spanisch'):
            word = 'spanisch'
        result.append(ALIASES.get(word, [word]))
    return result


def provider_terms(keywords):
    terms = []
    for keyword in keywords:
        parts = groups(keyword)
        # Choose the role/core term, avoiding isolated modifiers as OR alternatives.
        if len(parts) == 1:
            anchors = parts[0]
        else:
            ignored = set(ALIASES['leitung'] + ALIASES['rumaenisch'] + ALIASES['spanisch'] + ['junior', 'senior'])
            useful = [part for part in parts if not set(part).issubset(ignored)]
            anchors = min(useful or parts, key=lambda part: len(part))
        terms.extend(anchors)
    return list(dict.fromkeys(word for term in terms for word in term.split()))


def relevance(job, keywords):
    title, description = normalized(job.title), normalized(job.description_text)
    combined = title + ' ' + description
    title_hits, extract_hits = [], []
    for keyword in keywords:
        parts = groups(keyword)
        if all(contains(title, part) for part in parts):
            title_hits.append(keyword)
        elif all(contains(combined, part) for part in parts):
            extract_hits.append(keyword)
    level = 'title' if title_hits else 'description' if extract_hits else 'unconfirmed'
    return {'level': level, 'matched_keywords': title_hits or extract_hits,
            'explanation': {'title': 'El título coincide con el puesto buscado.',
                'description': 'Coincidencia en el extracto; revisa si describe el puesto o menciona otro trabajo.',
                'unconfirmed': 'Sin coincidencia clara con tus expresiones en el título y extracto disponibles.'}[level]}
