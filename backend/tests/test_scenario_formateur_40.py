#!/usr/bin/env python3
"""Scénario honnête : un formateur anime un cours avec 40 étudiants.

Chaque étudiant joue un rôle réaliste : arrivées décalées, réponses bonnes /
mauvaises / partielles / absentes, questions posées, réactions emoji,
déconnexions en cours de séance. Le formateur navigue, diffuse la correction,
fait une annonce, consulte résultats, stats et exports.

Six scénarios indépendants, tous sur la même instance éphémère :
  [1] cours complet 11 slides / 40 étudiants (arrivées tardives, reconnexion
      par jeton, correction, annonce, kick, stats toutes slides, exports CSV
      vérifiés ligne à ligne, résultats par étudiant) ;
  [2] verrouillage par compte à rebours (réponse refusée après la deadline) ;
  [3] planification : live planifié puis activé automatiquement par le timer ;
  [4] mode anonyme : identités masquées dans results ET dans tous les CSV ;
  [5] mode autonome : progression perso, verrouillage après réponse, correction
      après_question / jamais / à_la_fin, récapitulatif élève ;
  [6] agrégation multi-sessions : student-results et export événement sur
      plusieurs lives du même événement ;
  [7] campagne de cas limites : étudiants difficiles (mauvais code, nom
      vide/trop long, double join, jetons bidons, réponses hors limites) et
      appels formateur adverses (goto hors bornes, correction sur slide sans
      corrigé, kick, arrêt puis appels refusés) ;
  [8] WebSocket élève en mode autonome : current à la connexion, ping/pong,
      answer_locked, slide_changed, session_ended.

Ne touche jamais au ClassLive de production : instance éphémère sur un port
libre, workspace SQLite temporaire, tout est détruit à la fin.
"""
from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_reseau_multiclients import Server, PASSWORD, req, auth

# ── Profils des 40 étudiants ────────────────────────────────────────────────
PRENOMS = ["Marie", "Jean", "Léa", "Paul", "Emma", "Hugo", "Chloé", "Louis",
           "Camille", "Nathan", "Inès", "Lucas", "Sarah", "Tom", "Manon",
           "Adam", "Zoé", "Noah", "Jade", "Gabriel", "Louise", "Raphaël",
           "Alice", "Arthur", "Lina", "Jules", "Rose", "Marius", "Nina",
           "Théo", "Anna", "Victor", "Eva", "Antoine", "Mila", "Simon",
           "Léonie", "Maxime", "Juliette", "Baptiste"]
NOMS = ["Dupont", "Martin", "Bernard", "Petit", "Durand", "Leroy", "Moreau",
        "Simon", "Laurent", "Lefebvre", "Michel", "Garcia", "David", "Bertrand",
        "Roux", "Vincent", "Fournier", "Morel", "Girard", "Andre", "Mercier",
        "Blanc", "Guerin", "Boyer", "Garnier", "Chevalier", "Francois", "Legrand",
        "Gauthier", "Rousseau", "Blanchard", "Clement", "Bonnet", "Lambert",
        "Fontaine", "Rey", "Henry", "Robin", "Masson", "Marchand"]

# Répartition réaliste des comportements de réponse (par slide d'exercice).
# 0 = absent, 1 = répond, 2 = répond puis modifie sa réponse.
BEHAVIOUR = {
    'Q': [1]*28 + [2]*6 + [0]*6,   # QCM : 28 répondent, 6 modifient, 6 absents
    'P': [1]*30 + [0]*10,          # sondage : 30 répondent
    'F': [1]*25 + [0]*15,          # texte libre : 25 répondent
    'N': [1]*22 + [0]*18,          # nuage de mots
    'L': [1]*33 + [0]*7,           # échelle
    'I': [1]*20 + [0]*20,          # pin image
    'A': [1]*26 + [0]*14,          # associer
    'O': [1]*24 + [0]*16,          # ordonner
    'R': [1]*23 + [0]*17,          # classer
    'T': [1]*27 + [0]*13,          # texte à trous
}

ORDER = ['Introduction', 'QCM couches', 'Sondage expérience',
         'Texte libre', 'Nuage de mots', 'Échelle', 'Pin image',
         'Associer', 'Ordonner', 'Classifier', 'Texte à trous']
KINDS = ['C', 'Q', 'P', 'F', 'N', 'L', 'I', 'A', 'O', 'R', 'T']

QCM_CONTENT = ('---\nclasslive_answer:\n  selected: [B]\n---\n'
               '# Question ?\n- A\n- B')


# ── Helpers mutualisés (création / démarrage / arrêt) ───────────────────────

def make_group_event(client, trainer, group, event):
    g = req(client, 'POST', '/api/v1/groups', token=trainer,
            json={'group': group}).json()['group']
    e = req(client, 'POST', '/api/v1/events', token=trainer,
            json={'group': g, 'title': event}).json()['title']
    return g, e


def add_slide(client, trainer, base, title, kind, content):
    r = req(client, 'POST', base, token=trainer,
            json={'title': title, 'slide_type': kind, 'content': content})
    return r.json()['slide']


def make_live(client, trainer, group, event, slides, **live_kwargs):
    """Crée groupe + événement + slides, démarre le live.
    slides = [(title, kind, content), ...]. Renvoie le contexte complet."""
    g, e = make_group_event(client, trainer, group, event)
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    for title, kind, content in slides:
        add_slide(client, trainer, base, title, kind, content)
    live = req(client, 'POST', '/api/v1/live/start', token=trainer,
               json={'group': g, 'title': e, 'reactions_enabled': True, 'questions_enabled': True, **live_kwargs}).json()
    return {'g': g, 'e': e, 'base': base, **live}


def teardown_live(client, trainer, ctx):
    """Arrête le live, le supprime, puis supprime événement et groupe."""
    req(client, 'POST', f"/api/v1/live/{ctx['live_id']}/stop", token=trainer)
    req(client, 'DELETE', f"/api/v1/live/{ctx['live_id']}", token=trainer)
    req(client, 'DELETE', f"/api/v1/groups/{ctx['g']}/events/{ctx['e']}/sessions", token=trainer)
    req(client, 'DELETE', f"/api/v1/groups/{ctx['g']}/events/{ctx['e']}", token=trainer)
    req(client, 'DELETE', f"/api/v1/groups/{ctx['g']}", token=trainer)


def join_student(client, code, nom, prenom):
    r = client.post('/api/v1/student/join', json={
        'session_code': code, 'nom': nom, 'prenom': prenom})
    assert r.status_code == 200, r.text
    return r.json()['student_session_id'], r.json()['participation_id']


def student_headers(token):
    return {'Authorization': 'Bearer ' + token}


def read_csv(resp):
    assert resp.status_code == 200, resp.text
    return list(csv.DictReader(io.StringIO(resp.content.decode('utf-8-sig')),
                               delimiter=';'))


def build_course(client, trainer, group='BTS SIO - Réseaux', event='Cours TCP IP'):
    """Le formateur prépare un cours réaliste de 11 slides."""
    g, e = make_group_event(client, trainer, group, event)
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    slides = {}
    def add(title, kind, content):
        slides[title] = add_slide(client, trainer, base, title, kind, content)
    add('Introduction', 'C', '# Bienvenue\n\nAujourd\'hui : les fondamentaux TCP/IP.')
    add('QCM couches', 'Q',
        '---\nclasslive_answer:\n  selected: [B]\n---\n# Quelle couche gère le routage ?\n- A: Liaison\n- B: Réseau\n- C: Transport')
    add('Sondage expérience', 'P', '# Avez-vous déjà configuré un routeur ?\n- Oui\n- Non')
    add('Texte libre', 'F', '# Définissez en une phrase ce qu\'est une adresse IP.')
    add('Nuage de mots', 'N', '# Citez 3 mots associés à TCP.')
    add('Échelle', 'L', '# Niveau de confort avec le modèle OSI (1 à 5).')
    add('Pin image', 'I', '# Placez le pin sur le schéma du réseau.')
    add('Associer', 'A', '# Associez chaque protocole à son port.\n\n- HTTP: 80\n- HTTPS: 443\n- SSH: 22')
    add('Ordonner', 'O', '# Remettez dans l\'ordre les étapes d\'une connexion TCP.')
    add('Classifier', 'R', '# Classez ces protocoles : transport ou application.')
    add('Texte à trous', 'T',
        '---\nclasslive_answer:\n  selected: [TCP]\n---\n# Complétez : le protocole ___ garantit la fiabilité.')
    return g, e, base, slides


def answer_for(kind, i):
    """Réponse plausible pour l'étudiant i sur la slide de type kind."""
    if kind == 'Q':
        # 22 bons, 6 mauvais, 6 modifient (bon -> mauvais)
        if i % 7 == 0:
            return {'selected': ['A']}   # mauvais
        return {'selected': ['B']}       # bon
    if kind == 'P':
        return {'selected': ['Oui' if i % 3 else 'Non']}
    if kind == 'F':
        return {'text': f'Une adresse IP identifie une machine sur le réseau (étudiant {i}).'}
    if kind == 'N':
        return {'words': ['fiabilité', 'port', 'paquet']}
    if kind == 'L':
        return {'value': 1 + (i % 5)}
    if kind == 'I':
        return {'x': round(0.1 + 0.8 * (i % 10) / 9, 3), 'y': round(0.2 + 0.6 * (i % 7) / 6, 3)}
    if kind == 'A':
        return {'pairs': {'HTTP': '80', 'HTTPS': '443', 'SSH': '22'}}
    if kind == 'O':
        return {'order': ['SYN', 'SYN-ACK', 'ACK']}
    if kind == 'R':
        return {'categories': {'TCP': 'transport', 'HTTP': 'application', 'UDP': 'transport'}}
    if kind == 'T':
        return {'blanks': ['TCP']}
    return {'selected': ['B']}


# ── [1] Cours complet : 11 slides, 40 étudiants ─────────────────────────────

def scenario_cours_40(client, trainer):
    g, e, base, slides = build_course(client, trainer)
    live = req(client, 'POST', '/api/v1/live/start', token=trainer,
               json={'group': g, 'title': e, 'reactions_enabled': True, 'questions_enabled': True}).json()
    lid, code = live['live_id'], live['session_code']
    print(f'[1] Live démarré : {lid} (code {code})')

    # ── Arrivées décalées : 36 étudiants au début, 4 rejoignent en cours ──
    tokens, pids = [], []
    for i in range(36):
        tok, pid = join_student(client, code, NOMS[i], PRENOMS[i])
        tokens.append(tok)
        pids.append(pid)
        if i % 10 == 9:
            time.sleep(0.3)  # petits groupes d'arrivée
    print(f'[1] {len(tokens)} étudiants inscrits au début, jetons uniques : '
          f'{len(set(tokens)) == 36}')

    answered = {i: 0 for i in range(40)}
    joined = set(range(36))
    late = [36, 37, 38, 39]

    for idx, (title, kind) in enumerate(zip(ORDER, KINDS)):
        if idx > 0:
            req(client, 'POST', f'/api/v1/live/{lid}/next', token=trainer)
        if kind == 'C':
            continue  # slide de contenu, pas de réponse
        for i in range(40):
            if i not in joined:
                continue  # pas encore arrivé
            b = BEHAVIOUR[kind][i]
            if b == 0:
                continue  # absent
            h = student_headers(tokens[i])
            r = client.post('/api/v1/student/answers', headers=h,
                            json={'answer': answer_for(kind, i)})
            assert r.status_code == 200, (kind, i, r.text)
            answered[i] += 1
            if b == 2:  # l'étudiant change d'avis
                r2 = client.post('/api/v1/student/answers', headers=h,
                                 json={'answer': answer_for(kind, i)})
                assert r2.status_code == 200, (kind, i, r2.text)
        # Quelques étudiants posent des questions en cours de route
        if idx in (1, 3, 8):
            for i in range(0, 40, 13):
                if i in joined:
                    client.post('/api/v1/student/questions',
                                headers=student_headers(tokens[i]),
                                json={'text': f'Question de {PRENOMS[i]} sur {title} ?'})
        # Réactions emoji éparses
        if idx in (2, 5):
            for i in range(0, 40, 5):
                if i in joined:
                    client.post('/api/v1/student/reaction',
                                headers=student_headers(tokens[i]),
                                json={'emoji': '👍' if i % 2 else '🤔'})
        # Arrivées tardives : 4 étudiants rejoignent après le QCM (idx 1)
        if idx == 1:
            for i in late:
                tok, pid = join_student(client, code, NOMS[i], PRENOMS[i])
                tokens.append(tok)
                pids.append(pid)
                joined.add(i)
            print(f'[1] 4 étudiants arrivés en retard (total {len(tokens)}).')
    print('[1] Parcours des 11 slides terminé.')

    # ── Reconnexion par jeton : un étudiant « perd le Wi-Fi » et revient ──
    resume = req(client, 'POST', '/api/v1/student/resume',
                 token=tokens[0]).json()
    assert resume['nom'] == NOMS[0] and resume['prenom'] == PRENOMS[0], resume
    assert resume['current']['number'] == 11, resume  # dernière slide
    print('[1] Reconnexion par jeton OK (slide courante conservée).')

    # ── Le formateur diffuse la correction sur le QCM ──
    req(client, 'POST', f'/api/v1/live/{lid}/goto', token=trainer,
        json={'number': 2})
    req(client, 'POST', f'/api/v1/live/{lid}/correction/show', token=trainer)
    # L'étudiant voit la correction tant qu'elle est affichée
    cur = req(client, 'GET', '/api/v1/student/current',
              token=tokens[0]).json()
    assert cur['correction_visible'] is True and cur.get('correction') == {'selected': ['B']}, cur
    # Réponse refusée pendant l'affichage de la correction
    blocked = client.post('/api/v1/student/answers',
                          headers=student_headers(tokens[0]),
                          json={'answer': {'selected': ['A']}})
    assert blocked.status_code == 409, blocked.text
    req(client, 'POST', f'/api/v1/live/{lid}/correction/hide', token=trainer)
    cur = req(client, 'GET', '/api/v1/student/current',
              token=tokens[0]).json()
    assert cur['correction_visible'] is False and 'correction' not in cur, cur
    print('[1] Correction diffusée puis masquée, réponses bloquées pendant l\'affichage.')

    # ── Annonce du formateur, visible par les étudiants ──
    req(client, 'POST', f'/api/v1/live/{lid}/announce', token=trainer,
        json={'text': 'Pause de 5 minutes, puis exercice pratique.'})
    cur = req(client, 'GET', '/api/v1/student/current',
              token=tokens[0]).json()
    assert cur['announcement'] == 'Pause de 5 minutes, puis exercice pratique.', cur
    print('[1] Annonce diffusée et visible côté étudiant.')

    # ── Vérifications formateur ──
    status = req(client, 'GET', f'/api/v1/live/{lid}/status', token=trainer).json()
    assert status['number'] == 2, status
    students = req(client, 'GET', f'/api/v1/live/{lid}/students', token=trainer).json()
    assert students['total_students'] == 40, students
    results = req(client, 'GET', f'/api/v1/live/{lid}/results', token=trainer).json()
    assert len(results['results']) == 40, results
    assert 'points' not in json.dumps(results), 'Notation présente'
    # Chaque étudiant a répondu au nombre attendu de slides
    for i, r in enumerate(results['results']):
        assert r['answered'] == answered[i], (i, r['answered'], answered[i])
    print('[1] Résultats : 40 étudiants, réponses cohérentes, sans notation.')

    # Stats agrégées : slide courante ET toutes les slides
    stats = req(client, 'GET', f'/api/v1/live/{lid}/stats', token=trainer).json()
    print('[1] Stats agrégées OK :', json.dumps(stats)[:200])
    all_stats = req(client, 'GET', f'/api/v1/live/{lid}/stats', token=trainer,
                    params={'all': 'true'}).json()
    assert len(all_stats['slides']) == 11, len(all_stats['slides'])
    # stats compte les lignes brutes (les réponses modifiées comptent double)
    raw_expected = sum(answered.values()) + sum(
        1 for kind in KINDS if kind != 'C'
        for i in range(40) if i in joined and BEHAVIOUR[kind][i] == 2)
    assert sum(s['answered'] for s in all_stats['slides']) == raw_expected, all_stats
    assert all(s['answered'] <= 40 for s in all_stats['slides']), all_stats
    print(f"[1] Stats toutes slides : 11 slides, {raw_expected} réponses brutes au total.")

    # Questions posées par les étudiants
    qs = req(client, 'GET', f'/api/v1/live/{lid}/questions', token=trainer).json()
    qlist = qs['questions']
    print(f'[1] {len(qlist)} questions posées par les étudiants.')
    # Le formateur répond à la première et la marque résolue
    if qlist:
        qid = qlist[0]['id']
        req(client, 'POST', f'/api/v1/live/{lid}/questions/{qid}/answer',
            token=trainer, json={'text': 'Bonne question, on y revient.'})
        req(client, 'POST', f'/api/v1/live/{lid}/questions/{qid}/toggle', token=trainer)

    # Réactions
    reac = req(client, 'GET', f'/api/v1/live/{lid}/reactions', token=trainer).json()
    print(f'[1] Réactions : {reac["total"]} au total, {reac["counts"]}')

    # ── Exports CSV : contenu vérifié, pas seulement le nombre de lignes ──
    rows = read_csv(client.get(f'/api/v1/live/{lid}/export.csv',
                               headers=student_headers(trainer)))
    assert set(rows[0]) == {'live_id', 'nom', 'prenom', 'date_session', 'slide',
                            'reponse_json', 'date_reponse'}, rows[0]
    assert 'points' not in rows[0], 'Notation dans le CSV'
    # Chaque ligne de réponse est attribuée au bon étudiant
    by_name = {}
    for row in rows:
        by_name.setdefault((row['nom'], row['prenom']), 0)
        by_name[(row['nom'], row['prenom'])] += 1
    for i, r in enumerate(results['results']):
        assert by_name.get((r['nom'], r['prenom']), 0) == r['answered'], \
            (r['nom'], r['prenom'], by_name.get((r['nom'], r['prenom'])), r['answered'])
    print(f'[1] Export session : {len(rows)} lignes, attribution par étudiant vérifiée.')

    for name, path, cols in [
        ('présence', f'/api/v1/live/{lid}/presence.csv',
         {'live_id', 'nom', 'prenom', 'statut', 'rejoint_le', 'derniere_activite', 'reponses'}),
        ('questions', f'/api/v1/live/{lid}/questions.csv',
         {'live_id', 'question_id', 'nom', 'prenom', 'question', 'repondu', 'reponse', 'date_question', 'date_reponse'}),
        ('réactions', f'/api/v1/live/{lid}/reactions.csv',
         {'live_id', 'emoji', 'nombre'}),
    ]:
        rrows = read_csv(client.get(path, headers=student_headers(trainer)))
        assert set(rrows[0]) == cols, (name, rrows[0])
        print(f'[1] Export {name} : {len(rrows)} lignes, colonnes vérifiées.')

    # ── Résultats par étudiant (toutes sessions de l'événement) ──
    sr = req(client, 'GET',
             f'/api/v1/groups/{g}/events/{e}/student-results',
             token=trainer, params={'nom': NOMS[0], 'prenom': PRENOMS[0]}).json()
    assert sr['total_answers'] == answered[0], (sr['total_answers'], answered[0])
    print(f'[1] Résultats par étudiant ({NOMS[0]} {PRENOMS[0]}) : '
          f'{sr["total_answers"]} réponses.')

    # ── Kick : le formateur retire un participant en cours de séance ──
    kicked_pid = pids[39]
    req(client, 'DELETE', f'/api/v1/live/{lid}/students/{kicked_pid}', token=trainer)
    students = req(client, 'GET', f'/api/v1/live/{lid}/students', token=trainer).json()
    assert students['total_students'] == 39, students
    results = req(client, 'GET', f'/api/v1/live/{lid}/results', token=trainer).json()
    assert len(results['results']) == 39
    assert all(r['nom'] != NOMS[39] for r in results['results']), 'Étudiant expulsé encore présent'
    print('[1] Kick : participant retiré, ses réponses supprimées (39 restants).')

    # ── Fin de séance : arrêt, archive, nettoyage ──
    teardown_live(client, trainer, {'g': g, 'e': e, 'live_id': lid})
    print('[1] Séance terminée et données de test nettoyées.')


# ── [2] Verrouillage par compte à rebours ───────────────────────────────────

def scenario_verrouillage(client, trainer):
    """Compte à rebours par question : réponse refusée après la deadline."""
    ctx = make_live(client, trainer, 'Verrouillage', 'Timing',
                    slides=[('QCM simple', 'Q', QCM_CONTENT)],
                    timing='par_question', timing_seconds=1)
    lid, code = ctx['live_id'], ctx['session_code']
    tok, _ = join_student(client, code, 'Durand', 'Marie')
    h = student_headers(tok)
    # Réponse immédiate acceptée
    assert client.post('/api/v1/student/answers', headers=h,
                       json={'answer': {'selected': ['B']}}).status_code == 200
    time.sleep(1.5)  # la deadline (1 s) est dépassée
    # Réponse refusée : temps écoulé
    late = client.post('/api/v1/student/answers', headers=h,
                       json={'answer': {'selected': ['A']}})
    assert late.status_code == 409, late.text
    print('[2] Verrouillage par compte à rebours : réponse refusée après la deadline.')
    teardown_live(client, trainer, ctx)


# ── [3] Planification + activation automatique ──────────────────────────────

def scenario_planification(client, trainer):
    """Live planifié (start_at proche) : statut scheduled, listed, puis activé
    automatiquement par le timer ; un étudiant peut alors rejoindre et répondre."""
    ctx = make_live(client, trainer, 'Planification', 'Prévu',
                    slides=[('QCM simple', 'Q', QCM_CONTENT)],
                    start_at=(datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat())
    lid, code = ctx['live_id'], ctx['session_code']
    assert ctx['status'] == 'scheduled', ctx
    sched = req(client, 'GET', '/api/v1/live/scheduled', token=trainer).json()
    assert any(s['id'] == lid for s in sched['scheduled']), sched
    st = req(client, 'GET', f'/api/v1/live/{lid}/status', token=trainer).json()
    assert st['status'] == 'scheduled', st
    # Attente de l'activation automatique (timer armé au démarrage)
    deadline_poll = time.time() + 10
    while time.time() < deadline_poll:
        st = req(client, 'GET', f'/api/v1/live/{lid}/status', token=trainer).json()
        if st['status'] == 'running':
            break
        time.sleep(0.25)
    assert st['status'] == 'running', st
    sched = req(client, 'GET', '/api/v1/live/scheduled', token=trainer).json()
    assert all(s['id'] != lid for s in sched['scheduled']), sched
    # Une fois activé, un étudiant rejoint et répond
    tok, _ = join_student(client, code, 'Leroy', 'Emma')
    r = client.post('/api/v1/student/answers', headers=student_headers(tok),
                    json={'answer': {'selected': ['B']}})
    assert r.status_code == 200, r.text
    print('[3] Live planifié : scheduled, activé automatiquement par le timer, utilisable.')
    teardown_live(client, trainer, ctx)


# ── [4] Mode anonyme ────────────────────────────────────────────────────────

def scenario_anonyme(client, trainer):
    """Mode anonyme : identités masquées dans results ET dans tous les exports
    CSV, mais student-results par nom réel fonctionne toujours."""
    ctx = make_live(client, trainer, 'Anonymat', 'Anonyme',
                    slides=[('QCM simple', 'Q', QCM_CONTENT)],
                    anonymous=True)
    lid, code = ctx['live_id'], ctx['session_code']
    assert ctx['anonymous'] is True
    tok, _ = join_student(client, code, 'Dupont', 'Marie')
    h = student_headers(tok)
    client.post('/api/v1/student/answers', headers=h,
                json={'answer': {'selected': ['B']}})
    client.post('/api/v1/student/questions', headers=h,
                json={'text': 'Question anonyme ?'})
    res = req(client, 'GET', f'/api/v1/live/{lid}/results', token=trainer).json()
    assert res['anonymous'] is True and res['results'][0]['nom'] == 'anonyme', res
    # Tous les exports CSV masquent les identités
    hdr = student_headers(trainer)
    rows = read_csv(client.get(f'/api/v1/live/{lid}/export.csv', headers=hdr))
    assert rows[0]['nom'] == 'anonyme' and rows[0]['prenom'] == '', rows[0]
    prows = read_csv(client.get(f'/api/v1/live/{lid}/presence.csv', headers=hdr))
    assert prows[0]['nom'] == 'anonyme' and prows[0]['prenom'] == '', prows[0]
    qrows = read_csv(client.get(f'/api/v1/live/{lid}/questions.csv', headers=hdr))
    assert qrows[0]['nom'] == 'anonyme' and qrows[0]['question'] == 'Question anonyme ?', qrows[0]
    # L'identité reste traçable par nom/prénom pour le formateur
    sr = req(client, 'GET', f'/api/v1/groups/{ctx["g"]}/events/{ctx["e"]}/student-results',
             token=trainer, params={'nom': 'Dupont', 'prenom': 'Marie'}).json()
    assert sr['total_answers'] == 1, sr
    print('[4] Mode anonyme : results + tous les CSV masqués, traçabilité par nom conservée.')
    teardown_live(client, trainer, ctx)


# ── [5] Mode autonome ───────────────────────────────────────────────────────

def scenario_autonome(client, trainer):
    """Mode autonome : progression perso, next bloqué tant que l'exercice n'est
    pas répondu, verrouillage après réponse, correction selon correction_mode,
    récapitulatif élève disponible seulement en fin de parcours."""
    slides = [
        ('QCM auto', 'Q', QCM_CONTENT),
        ('Texte libre auto', 'F', '# Votre définition de TCP.'),
        ('Conclusion', 'C', '# Fin du parcours autonome.'),
    ]
    ctx = make_live(client, trainer, 'Autonome', 'Parcours perso',
                    slides=slides, mode='autonome', correction='après_question')
    lid, code = ctx['live_id'], ctx['session_code']
    tok, _ = join_student(client, code, 'Moreau', 'Chloé')
    h = student_headers(tok)

    cur = req(client, 'GET', '/api/v1/student/current', token=tok).json()
    assert cur['mode'] == 'autonome' and cur['number'] == 1 and cur['locked'] is False \
        and cur['finished'] is False, cur
    # next bloqué sur un exercice non répondu
    blocked = client.post('/api/v1/student/next', headers=h)
    assert blocked.status_code == 409, blocked.text
    # réponse -> verrouillée, correction visible (après_question)
    r = client.post('/api/v1/student/answers', headers=h,
                    json={'answer': {'selected': ['B']}})
    assert r.status_code == 200 and r.json()['locked'] is True, r.text
    again = client.post('/api/v1/student/answers', headers=h,
                        json={'answer': {'selected': ['A']}})
    assert again.status_code == 409, again.text  # déjà verrouillée
    cur = req(client, 'GET', '/api/v1/student/current', token=tok).json()
    assert cur['locked'] is True and cur['correction'] == {'selected': ['B']}, cur
    # next débloqué, slide suivante
    cur = req(client, 'POST', '/api/v1/student/next', token=tok).json()
    assert cur['number'] == 2, cur
    # récap perso indisponible tant que le parcours n'est pas fini
    own = client.get('/api/v1/student/results', headers=h)
    assert own.status_code == 409, own.text
    # slide F répondue, puis slide C, puis next sur la dernière -> terminé
    assert client.post('/api/v1/student/answers', headers=h,
                       json={'answer': {'text': 'TCP garantit la livraison ordonnée.'}}).status_code == 200
    cur = req(client, 'POST', '/api/v1/student/next', token=tok).json()
    assert cur['number'] == 3 and cur['finished'] is False, cur
    cur = req(client, 'POST', '/api/v1/student/next', token=tok).json()
    assert cur['finished'] is True, cur
    # next après la fin -> refusé
    done = client.post('/api/v1/student/next', headers=h)
    assert done.status_code == 409, done.text
    # récap perso disponible : 2 réponses, correction du QCM incluse
    own = req(client, 'GET', '/api/v1/student/results', token=tok).json()
    assert own['finished_at'] and own['total_slides'] == 3 and own['answered'] == 2, own
    by_num = {s['number']: s for s in own['slides']}
    assert by_num[1]['correction'] == {'selected': ['B']}
    assert 'correction' not in by_num[2]  # F sans classlive_answer
    assert by_num[3]['answered'] is False
    # le formateur voit aussi le résultat (identifié, mode autonome non anonyme)
    res = req(client, 'GET', f'/api/v1/live/{lid}/results', token=trainer).json()
    assert res['results'][0]['nom'] == 'Moreau' and res['results'][0]['answered'] == 2, res
    print('[5] Autonome après_question : next bloqué, verrouillage, correction, récap de fin.')
    teardown_live(client, trainer, ctx)

    # correction_mode='jamais' : aucune correction, même en fin de parcours
    ctx = make_live(client, trainer, 'Autonome', 'Jamais',
                    slides=[('QCM auto', 'Q', QCM_CONTENT)],
                    mode='autonome', correction='jamais')
    tok, _ = join_student(client, ctx['session_code'], 'Petit', 'Hugo')
    h = student_headers(tok)
    client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['B']}})
    cur = req(client, 'POST', '/api/v1/student/next', token=tok).json()
    assert cur['finished'] is True, cur
    cur = req(client, 'GET', '/api/v1/student/current', token=tok).json()
    assert 'correction' not in cur, cur
    own = req(client, 'GET', '/api/v1/student/results', token=tok).json()
    assert 'correction' not in own['slides'][0], own
    print('[5] Autonome jamais : aucune correction affichée.')
    teardown_live(client, trainer, ctx)

    # correction_mode='à_la_fin' : correction seulement une fois terminé
    ctx = make_live(client, trainer, 'Autonome', 'ALaFin',
                    slides=[('QCM auto', 'Q', QCM_CONTENT)],
                    mode='autonome', correction='à_la_fin')
    tok, _ = join_student(client, ctx['session_code'], 'Bernard', 'Léa')
    h = student_headers(tok)
    client.post('/api/v1/student/answers', headers=h, json={'answer': {'selected': ['B']}})
    cur = req(client, 'GET', '/api/v1/student/current', token=tok).json()
    assert cur['finished'] is False and 'correction' not in cur, cur
    cur = req(client, 'POST', '/api/v1/student/next', token=tok).json()
    assert cur['finished'] is True, cur
    cur = req(client, 'GET', '/api/v1/student/current', token=tok).json()
    assert cur['correction'] == {'selected': ['B']}, cur
    print('[5] Autonome à_la_fin : correction révélée uniquement en fin de parcours.')
    teardown_live(client, trainer, ctx)

    # timing par_question en autonome : timer par élève démarré à la 1re vue
    ctx = make_live(client, trainer, 'Autonome', 'Timer',
                    slides=[('QCM auto', 'Q', QCM_CONTENT)],
                    mode='autonome', timing='par_question', timing_seconds=1,
                    correction='après_question')
    tok, _ = join_student(client, ctx['session_code'], 'Fournier', 'Zoé')
    h = student_headers(tok)
    cur = req(client, 'GET', '/api/v1/student/current', token=tok).json()
    assert cur['question_started_at'] and cur['expires_at'] and cur['locked'] is False, cur
    time.sleep(1.5)  # deadline (1 s) dépassée
    r = client.post('/api/v1/student/answers', headers=h,
                    json={'answer': {'selected': ['B']}})
    assert r.status_code == 409, r.text  # temps écoulé
    cur = req(client, 'GET', '/api/v1/student/current', token=tok).json()
    assert cur['locked'] is True and cur['correction'] == {'selected': ['B']}, cur
    # slide verrouillée -> next autorisé, fin du parcours ; récap : 0 réponse
    cur = req(client, 'POST', '/api/v1/student/next', token=tok).json()
    assert cur['finished'] is True, cur
    own = req(client, 'GET', '/api/v1/student/results', token=tok).json()
    assert own['answered'] == 0 and own['slides'][0]['answered'] is False, own
    print('[5] Autonome par_question : timer expiré -> réponse 409, slide verrouillée, correction affichée.')
    teardown_live(client, trainer, ctx)


# ── [6] Agrégation multi-sessions d'un même événement ───────────────────────

def scenario_multi_sessions(client, trainer):
    """Deux lives successifs sur le même événement : student-results agrège les
    deux sessions et l'export événement contient les deux live_id."""
    g, e = make_group_event(client, trainer, 'Multi', 'Séances multiples')
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    add_slide(client, trainer, base, 'QCM simple', 'Q', QCM_CONTENT)

    lids = []
    for n in (1, 2):
        live = req(client, 'POST', '/api/v1/live/start', token=trainer,
                   json={'group': g, 'title': e}).json()
        lids.append(live['live_id'])
        tok, _ = join_student(client, live['session_code'], 'Durand', 'Marie')
        r = client.post('/api/v1/student/answers', headers=student_headers(tok),
                        json={'answer': {'selected': ['B']}})
        assert r.status_code == 200, r.text
        # on arrête mais on garde la session : c'est l'agrégation qui est testée
        req(client, 'POST', f"/api/v1/live/{live['live_id']}/stop", token=trainer)

    sessions = req(client, 'GET', f'/api/v1/groups/{g}/events/{e}/sessions',
                   token=trainer).json()
    assert len(sessions['sessions']) == 2, sessions
    sr = req(client, 'GET', f'/api/v1/groups/{g}/events/{e}/student-results',
             token=trainer, params={'nom': 'Durand', 'prenom': 'Marie'}).json()
    assert sr['total_answers'] == 2 and len(sr['sessions']) == 2, sr
    rows = read_csv(client.get(f'/api/v1/groups/{g}/events/{e}/export.csv',
                               headers=student_headers(trainer)))
    assert len(rows) == 2 and {r['live_id'] for r in rows} == set(lids), rows
    assert all(r['nom'] == 'Durand' for r in rows), rows
    print('[6] Multi-sessions : 2 lives agrégés dans student-results et l\'export événement.')

    req(client, 'DELETE', f'/api/v1/groups/{g}/events/{e}/sessions', token=trainer)
    req(client, 'DELETE', f'/api/v1/groups/{g}/events/{e}', token=trainer)
    req(client, 'DELETE', f'/api/v1/groups/{g}', token=trainer)


# ── [7] Campagne de cas limites ─────────────────────────────────────────────

def scenario_limites(client, trainer):
    """Étudiants difficiles + appels formateur adverses. Chaque assertion
    encode un comportement confirmé par sondage contre l'API réelle."""
    ctx = make_live(client, trainer, 'Limites', 'Adversarial',
                    slides=[
                        ('Intro', 'C', '# intro'),
                        ('QCM', 'Q', QCM_CONTENT),
                        ('QCM sans corrigé', 'Q', '# Q sans classlive_answer ?\n- A\n- B'),
                    ])
    lid, code = ctx['live_id'], ctx['session_code']
    H = student_headers(trainer)

    # ── Jointures adverses ──
    assert client.post('/api/v1/student/join',
                       json={'session_code': '000000', 'nom': 'X', 'prenom': 'Y'}).status_code == 404
    for bad in ({'nom': '', 'prenom': 'Y'}, {'nom': '   ', 'prenom': 'Y'},
                {'nom': 'x' * 101, 'prenom': 'Y'}, {'nom': 'X', 'prenom': ''}):
        r = client.post('/api/v1/student/join', json={'session_code': code, **bad})
        assert r.status_code == 422, (bad, r.status_code, r.text)
    assert client.post('/api/v1/student/join',
                       json={'session_code': code, 'nom': 'x' * 100, 'prenom': 'Y'}).status_code == 200
    # double join même identité : autorisé (contrat documenté), deux participations
    t1, p1 = join_student(client, code, 'Durand', 'Marie')
    t2, p2 = join_student(client, code, 'Durand', 'Marie')
    assert p1 != p2
    st = req(client, 'GET', f'/api/v1/live/{lid}/students', token=trainer).json()
    assert st['total_students'] == 3, st  # 'x'*100 + les deux Durand
    h1 = student_headers(t1)
    # jeton bidon / sans header
    assert client.post('/api/v1/student/resume',
                       headers={'Authorization': 'Bearer bidon'}).status_code == 401
    assert client.post('/api/v1/student/resume').status_code == 401

    # ── Réponse sur slide de contenu -> 409 ──
    assert client.post('/api/v1/student/answers', headers=h1,
                       json={'answer': {'selected': ['A']}}).status_code == 409

    # ── Navigation formateur hors bornes ──
    assert client.post(f'/api/v1/live/{lid}/goto', headers=H, json={'number': 0}).status_code == 422
    assert client.post(f'/api/v1/live/{lid}/goto', headers=H, json={'number': -1}).status_code == 422
    assert client.post(f'/api/v1/live/{lid}/goto', headers=H, json={'number': 999}).status_code == 404
    assert client.post(f'/api/v1/live/{lid}/goto', headers=H, json={'number': '2'}).status_code == 422

    # ── Correction : slide C -> 409, Q sans corrigé -> 409, Q avec -> ok ──
    req(client, 'POST', f'/api/v1/live/{lid}/goto', token=trainer, json={'number': 1})
    assert client.post(f'/api/v1/live/{lid}/correction/show', headers=H).status_code == 409
    req(client, 'POST', f'/api/v1/live/{lid}/goto', token=trainer, json={'number': 3})
    assert client.post(f'/api/v1/live/{lid}/correction/show', headers=H).status_code == 409
    req(client, 'POST', f'/api/v1/live/{lid}/goto', token=trainer, json={'number': 2})
    req(client, 'POST', f'/api/v1/live/{lid}/correction/show', token=trainer)
    assert client.post('/api/v1/student/answers', headers=h1,
                       json={'answer': {'selected': ['B']}}).status_code == 409
    req(client, 'POST', f'/api/v1/live/{lid}/correction/hide', token=trainer)
    # QCM durci au niveau forme : selected présent -> liste de chaînes
    assert client.post('/api/v1/student/answers', headers=h1,
                       json={'answer': {'selected': 'B'}}).status_code == 422
    assert client.post('/api/v1/student/answers', headers=h1,
                       json={'answer': {'selected': [1]}}).status_code == 422
    assert client.post('/api/v1/student/answers', headers=h1,
                       json={'answer': {}}).status_code == 200  # dict vide toléré (rétrocompat)
    assert client.post('/api/v1/student/answers', headers=h1,
                       json={'answer': {'selected': ['B']}}).status_code == 200
    # réponse modifiée après coup : la dernière est conservée
    assert client.post('/api/v1/student/answers', headers=h1,
                       json={'answer': {'selected': ['A']}}).status_code == 200
    res = req(client, 'GET', f'/api/v1/live/{lid}/results', token=trainer).json()
    durand = next(r for r in res['results'] if r['nom'] == 'Durand' and r['answered'] == 1)
    assert durand['answers'][0]['answer'] == {'selected': ['A']}, durand

    # ── Annonce : 500 car ok, 501 -> 422, persistée pour les arrivants tardifs ──
    assert client.post(f'/api/v1/live/{lid}/announce', headers=H,
                       json={'text': 'a' * 500}).status_code == 200
    assert client.post(f'/api/v1/live/{lid}/announce', headers=H,
                       json={'text': 'a' * 501}).status_code == 422
    req(client, 'POST', f'/api/v1/live/{lid}/announce', token=trainer,
        json={'text': 'Bienvenue !'})
    t3, _ = join_student(client, code, 'Leroy', 'Emma')
    cur = req(client, 'GET', '/api/v1/student/current', token=t3).json()
    assert cur['announcement'] == 'Bienvenue !', cur

    # ── Questions : 1000 car ok, 1001 -> 422, 50 max par élève ──
    assert client.post('/api/v1/student/questions', headers=h1,
                       json={'text': 'a' * 1000}).status_code == 200
    assert client.post('/api/v1/student/questions', headers=h1,
                       json={'text': 'a' * 1001}).status_code == 422
    for i in range(49):
        assert client.post('/api/v1/student/questions', headers=h1,
                           json={'text': f'q{i}'}).status_code == 200
    assert client.post('/api/v1/student/questions', headers=h1,
                       json={'text': 'q51'}).status_code == 409

    # ── Réactions : emoji 8 car ok, 9 car -> 422 ──
    assert client.post('/api/v1/student/reaction', headers=h1,
                       json={'emoji': 'x' * 8}).status_code == 200
    assert client.post('/api/v1/student/reaction', headers=h1,
                       json={'emoji': 'x' * 9}).status_code == 422

    # ── Réponses : >64 Ko -> 422, non-dict -> 422 ──
    assert client.post('/api/v1/student/answers', headers=h1,
                       json={'answer': {'selected': ['B'], 'pad': 'x' * 66000}}).status_code == 422
    assert client.post('/api/v1/student/answers', headers=h1,
                       json={'answer': [1, 2]}).status_code == 422

    # ── Kick : pid inexistant -> 404, bon pid -> 401 partout, double kick -> 404 ──
    assert client.delete(f'/api/v1/live/{lid}/students/999999', headers=H).status_code == 404
    assert client.delete(f'/api/v1/live/{lid}/students/{p1}', headers=H).status_code == 200
    assert client.post('/api/v1/student/resume', headers=h1).status_code == 401
    assert client.post('/api/v1/student/answers', headers=h1,
                       json={'answer': {'selected': ['B']}}).status_code == 401
    assert client.get('/api/v1/student/current', headers=h1).status_code == 401
    assert client.delete(f'/api/v1/live/{lid}/students/{p1}', headers=H).status_code == 404

    # ── Démarrages adverses ──
    assert client.post('/api/v1/live/start', headers=H, json={
        'group': ctx['g'], 'title': 'Autre', 'start_at': '2020-01-01T00:00:00+00:00'}).status_code == 422
    assert client.post('/api/v1/live/start', headers=H, json={
        'group': ctx['g'], 'title': 'Autre', 'mode': 'hybride'}).status_code == 422
    assert client.post('/api/v1/live/start', headers=H, json={
        'group': 'Nope', 'title': 'X'}).status_code == 404
    # 2e live sur le même événement pendant que le 1er tourne -> 409
    assert client.post('/api/v1/live/start', headers=H, json={
        'group': ctx['g'], 'title': ctx['e']}).status_code == 409

    # ── student-results inconnu -> 0 réponse ──
    sr = req(client, 'GET', f'/api/v1/groups/{ctx["g"]}/events/{ctx["e"]}/student-results',
             token=trainer, params={'nom': 'Inconnu', 'prenom': 'X'}).json()
    assert sr['total_answers'] == 0, sr

    # ── Export CSV sans aucune réponse : entête seule ──
    g2, e2 = make_group_event(client, trainer, 'Limites Vide', 'Vide')
    b2 = f'/api/v1/groups/{g2}/events/{e2}/slides'
    add_slide(client, trainer, b2, 'QCM', 'Q', QCM_CONTENT)
    live2 = req(client, 'POST', '/api/v1/live/start', token=trainer,
                json={'group': g2, 'title': e2}).json()
    rows = read_csv(client.get(f'/api/v1/live/{live2["live_id"]}/export.csv', headers=H))
    assert rows == [], rows
    teardown_live(client, trainer, {'g': g2, 'e': e2, 'live_id': live2['live_id']})

    # ── Après stop : join 404, next 409, endpoints élève 401, stop idempotent ──
    req(client, 'POST', f'/api/v1/live/{lid}/stop', token=trainer)
    assert client.post('/api/v1/student/join',
                       json={'session_code': code, 'nom': 'Z', 'prenom': 'Z'}).status_code == 404
    assert client.post(f'/api/v1/live/{lid}/next', headers=H).status_code == 409
    h3 = student_headers(t3)
    assert client.post('/api/v1/student/resume', headers=h3).status_code == 401
    assert client.get('/api/v1/student/current', headers=h3).status_code == 401
    assert client.post('/api/v1/student/answers', headers=h3,
                       json={'answer': {'selected': ['B']}}).status_code == 401
    assert client.post('/api/v1/student/reaction', headers=h3,
                       json={'emoji': '👍'}).status_code == 401
    assert req(client, 'POST', f'/api/v1/live/{lid}/stop', token=trainer).json()['status'] == 'ended'
    print('[7] Cas limites : joins adverses, tailles max, correction, kick, arrêt — tous conformes.')

    req(client, 'DELETE', f'/api/v1/live/{lid}', token=trainer)
    req(client, 'DELETE', f'/api/v1/groups/{ctx["g"]}/events/{ctx["e"]}/sessions', token=trainer)
    req(client, 'DELETE', f'/api/v1/groups/{ctx["g"]}/events/{ctx["e"]}', token=trainer)
    req(client, 'DELETE', f'/api/v1/groups/{ctx["g"]}', token=trainer)


# ── [8] WebSocket élève en mode autonome ────────────────────────────────────

def scenario_ws_autonome(client, trainer, base_http):
    """Flux WebSocket d'un élève en autonome : current à la connexion, ping/pong,
    answer_locked après réponse, slide_changed à chaque next, session_ended en fin."""
    from websockets.sync.client import connect
    ctx = make_live(client, trainer, 'WS Autonome', 'Flux',
                    slides=[('QCM auto', 'Q', QCM_CONTENT),
                            ('Fin', 'C', '# fin du parcours')],
                    mode='autonome', correction='après_question')
    lid, code = ctx['live_id'], ctx['session_code']
    tok, _ = join_student(client, code, 'Morel', 'Adam')
    h = student_headers(tok)

    def recv_until(ws, event, max_events=10):
        for _ in range(max_events):
            ev = json.loads(ws.recv(timeout=10))
            if ev.get('event') == event:
                return ev
        raise AssertionError(f'{event} non reçu')

    url = base_http.replace('http://', 'ws://') + '/api/v1/student/ws'
    with connect(url) as ws:
        ws.send(json.dumps({'token': tok}))
        first = json.loads(ws.recv(timeout=10))
        assert first['event'] == 'current' and first['current']['number'] == 1, first
        # ping/pong (heartbeat)
        ws.send(json.dumps({'event': 'ping'}))
        assert json.loads(ws.recv(timeout=10))['event'] == 'pong'
        # réponse -> verrouillée -> answer_locked
        assert client.post('/api/v1/student/answers', headers=h,
                           json={'answer': {'selected': ['B']}}).status_code == 200
        ev = recv_until(ws, 'answer_locked')
        assert ev['slide'].startswith('S001_Q_'), ev
        # next -> slide_changed (slide 2)
        req(client, 'POST', '/api/v1/student/next', token=tok)
        ev = recv_until(ws, 'slide_changed')
        assert ev['current']['number'] == 2, ev
        # next sur la dernière slide -> slide_changed puis session_ended
        req(client, 'POST', '/api/v1/student/next', token=tok)
        ev = recv_until(ws, 'session_ended')
        assert ev['live_id'] == lid, ev
    # après session_ended, le ping ferme la connexion (1008)
    print('[8] WebSocket autonome : current, pong, answer_locked, slide_changed, session_ended OK.')
    teardown_live(client, trainer, ctx)


def main():
    with tempfile.TemporaryDirectory(prefix='classlive-formateur-40-') as tmp:
        srv = Server(Path(tmp))
        srv.start()
        try:
            with httpx.Client(base_url=srv.base, timeout=30) as client:
                trainer = auth(client)
                scenario_cours_40(client, trainer)
                scenario_verrouillage(client, trainer)
                scenario_planification(client, trainer)
                scenario_anonyme(client, trainer)
                scenario_autonome(client, trainer)
                scenario_multi_sessions(client, trainer)
                scenario_limites(client, trainer)
                scenario_ws_autonome(client, trainer, srv.base)
            print('\nSUCCÈS : scénario formateur + 40 étudiants validé de bout en bout.')
        except Exception:
            print('\n--- Journaux du serveur éphémère ---\n' + srv.log_tail(), file=sys.stderr)
            raise
        finally:
            srv.stop()


if __name__ == '__main__':
    main()
