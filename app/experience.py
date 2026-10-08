import re


def required_experience_quotes(job):
    text = '\n'.join([job.title or '', job.description_text or ''])
    quotes = []
    for sentence in re.split(r'[\n.;!?]+', text):
        if re.search(r'\b(keine?|ohne|nicht erforderlich|nicht zwingend|wünschenswert|von Vorteil|idealerweise|optional)\b', sentence, re.I):
            continue
        pattern = (r'\b(?:mindestens\s+\d+\s+Jahre?\w*|mehrjährige\w*|mehrjaehrige\w*)\s+(?:\w+\s+){0,3}(?:Berufs)?erfahrung\b'
                   r'|\b(?:Berufs)?erfahrung\b.{0,70}\b(?:erforderlich|vorausgesetzt|zwingend|notwendig)\b')
        if re.search(pattern, sentence, re.I):
            quotes.append(sentence.strip()[:1000])
    return quotes
