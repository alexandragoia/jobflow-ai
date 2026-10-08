"""Local, reviewable preference suggestions; no paid model calls or automatic changes."""
import hashlib
import json
from collections import Counter, defaultdict

from sqlalchemy import select

from .experience import required_experience_quotes
from .job_identity import canonical_job_id
from .models import Job, JobFeedback, LearningDecision, SearchResult
from .schemas import SettingsPayload
from .scoring import LABELS
from .settings_service import public_settings, save_settings

REASONS = {
    'Demasiado teléfono': [('phone_3', -1), ('phone_4_5', -1)],
    'Mucho contacto con clientes': [('high_contact', -1)],
    'Demasiado físico': [('physical_high', -1)],
    'Teilzeit': [('part_time', -1)],
    'Titulación requerida': [('qualification', -1)],
    'Alemán demasiado avanzado': [('heavy_german', -1)],
    'Limpieza': [('cleaning', -1)], 'Almacén': [('warehouse', -1)], 'Ventas': [('sales', -1)],
    'No tengo la experiencia necesaria': [('required_experience', -1)],
    'No tiene nada que ver con lo que estoy buscando': [('keyword_title', 1), ('keyword_description', -1)],
}


def explicit_criteria(snapshot):
    signals = set()
    for factor in snapshot.get('factors', []):
        if factor.get('origin') != 'stated' or not factor.get('evidence'):
            continue
        for key, label in LABELS.items():
            if key not in ('keyword_title', 'keyword_description', 'qualification', 'required_experience') and label == factor.get('label'):
                signals.add(key)
    return signals


def suggestions(session):
    settings = public_settings()
    records = session.scalars(select(LearningDecision).order_by(LearningDecision.id.desc())).all()
    consumed = defaultdict(set)
    ignored = {row.proposal_id for row in records}
    for row in records:
        if row.state in ('accepted', 'undone'):
            consumed[(row.weight_key, row.direction)].update(item['job_id'] for item in json.loads(row.evidence_json))
    snapshots = {}
    # Keep one latest available snapshot per canonical offer, including merged identities.
    for row in session.scalars(select(SearchResult).order_by(SearchResult.id.desc())):
        identity = canonical_job_id(session, row.job_id)
        if identity not in snapshots:
            snapshots[identity] = json.loads(row.result_json or '{}')
    votes = defaultdict(dict)
    totals = Counter()
    unresolved = Counter()
    contexts = []
    seen = set()
    for feedback in session.scalars(select(JobFeedback).order_by(JobFeedback.updated_at.desc())):
        identity = canonical_job_id(session, feedback.job_id)
        if identity in seen:
            continue
        seen.add(identity)
        job = session.get(Job, identity)
        if not job:
            continue
        if feedback.interest_note and (feedback.saved or feedback.disposition == 'interested'):
            contexts.append({'job_id': identity, 'title': job.title, 'note': feedback.interest_note,
                             'conditional': feedback.interest_conditional})
        if feedback.disposition not in ('interested', 'rejected'):
            continue
        totals[feedback.disposition] += 1
        snapshot = snapshots.get(identity, {})
        reason = feedback.reason or 'Sin motivo'
        signals = []
        if feedback.disposition == 'rejected':
            signals = REASONS.get(reason, [])
            if reason == 'Sin motivo':
                signals = [(key, -1) for key in explicit_criteria(snapshot)]
            if reason == 'No tengo la experiencia necesaria':
                # The rejection explains your choice; it doesn't establish a job requirement.
                if not required_experience_quotes(job):
                    signals = []
            elif reason == 'Turno inadecuado':
                shift = snapshot.get('analysis', {}).get('shift_type', {})
                if shift.get('value') == 'two_shift' and shift.get('origin') == 'stated':
                    signals = [('two_shift', -1)]
            if not signals:
                unresolved[reason] += 1
        else:
            # Interest in a hypothetical variant does not endorse the advertised conditions.
            signals = [] if feedback.interest_conditional else [(key, 1) for key in explicit_criteria(snapshot)]
        for key, direction in set(signals):
            if key not in settings['weights']:
                continue
            evidence = required_experience_quotes(job) if key == 'required_experience' else []
            if feedback.disposition == 'interested' or reason == 'Sin motivo':
                evidence = [f['evidence'] for f in snapshot.get('factors', []) if f.get('label') == LABELS[key] and f.get('origin') == 'stated']
            votes[(key, direction)][identity] = {'job_id': identity, 'title': job.title,
                'disposition': feedback.disposition, 'reason': reason if feedback.disposition == 'rejected' else
                    'Me interesa' + (': ' + feedback.interest_note if feedback.interest_note else ''),
                'quotes': evidence}
    proposals = []
    for (key, direction), observations in votes.items():
        fresh = [item for identity, item in sorted(observations.items()) if identity not in consumed[(key, direction)]]
        opposite = [identity for identity in votes.get((key, -direction), {}) if identity not in consumed[(key, -direction)]]
        if len(fresh) < 3 or len(fresh) - len(opposite) < 2:
            continue
        current = settings['weights'][key]
        proposed = max(-40, min(40, current + direction * 3))
        if proposed == current:
            continue
        signature = json.dumps([key, direction, current, fresh, sorted(opposite)], sort_keys=True, ensure_ascii=False)
        proposal_id = hashlib.sha256(signature.encode()).hexdigest()
        if proposal_id in ignored:
            continue
        proposals.append({'id': proposal_id, 'weight_key': key, 'label': LABELS[key],
            'direction': direction, 'current': current, 'proposed': proposed,
            'support': len(fresh), 'opposing': len(opposite), 'evidence': fresh,
            'explanation': f'{len(fresh)} valoraciones apoyan este ajuste y {len(opposite)} apuntan en sentido contrario. Es una propuesta basada en tus decisiones, no una certeza sobre tus preferencias.'})
    proposals.sort(key=lambda item: (-(item['support'] - item['opposing']), item['weight_key']))
    history = [{'id': row.id, 'label': LABELS.get(row.weight_key, row.weight_key), 'state': row.state,
        'previous': row.previous_value, 'proposed': row.proposed_value, 'created_at': row.created_at.isoformat()}
        for row in records[:20]]
    return {'proposals': proposals, 'history': history, 'totals': dict(totals),
        'unresolved': [{'reason': reason, 'count': count} for reason, count in sorted(unresolved.items())],
        'minimum_support': 3, 'interest_contexts': contexts}


def update_weight(key, value):
    settings = public_settings()
    settings['weights'][key] = value
    payload = SettingsPayload(**{name: settings[name] for name in SettingsPayload.model_fields})
    save_settings(payload)


def decide(session, proposal_id, action):
    proposal = next((item for item in suggestions(session)['proposals'] if item['id'] == proposal_id), None)
    if proposal is None:
        raise ValueError('La propuesta ya no está vigente. Actualiza las recomendaciones.')
    record = LearningDecision(proposal_id=proposal_id, weight_key=proposal['weight_key'],
        direction=proposal['direction'], previous_value=proposal['current'], proposed_value=proposal['proposed'],
        state='accepted' if action == 'accept' else 'dismissed', evidence_json=json.dumps(proposal['evidence'], ensure_ascii=False))
    session.add(record)
    updated = False
    try:
        session.flush()
        if action == 'accept':
            update_weight(record.weight_key, record.proposed_value)
            updated = True
        session.commit()
    except Exception:
        session.rollback()
        if updated:
            update_weight(proposal['weight_key'], proposal['current'])
        raise
    return suggestions(session)


def undo(session, decision_id):
    record = session.get(LearningDecision, decision_id)
    if record is None or record.state != 'accepted':
        raise ValueError('Este ajuste no se puede deshacer.')
    if public_settings()['weights'][record.weight_key] != record.proposed_value:
        raise ValueError('Este peso cambió después. Revísalo en Qué suma y qué resta antes de modificarlo.')
    key, previous, proposed = record.weight_key, record.previous_value, record.proposed_value
    record.state = 'undone'
    updated = False
    try:
        session.flush()
        update_weight(key, previous)
        updated = True
        session.commit()
    except Exception:
        session.rollback()
        if updated:
            update_weight(key, proposed)
        raise
    return suggestions(session)
