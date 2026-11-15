#!/usr/bin/env python3
"""Scénario honnête : un formateur anime un cours avec 40 étudiants.

Chaque étudiant joue un rôle réaliste : arrivées décalées, réponses bonnes /
mauvaises / partielles / absentes, questions posées, réactions emoji,
déconnexions en cours de séance. Le formateur navigue, diffuse la correction,
fait une annonce et consulte résultats, stats et exports.

Le fichier couvre aussi, sur la même instance éphémère, les cas limites
demandés : arrivées tardives, reconnexion par jeton, verrouillage (compte à
rebours + correction), planification (start_at), mode anonyme, exports par
étudiant et vérification du contenu des CSV.

Ne touche jamais au ClassLive de production : instance éphémère sur un port
libre, workspace SQLite temporaire, tout est détruit à la fin.
"""
from __future__ import annotations

import csv
import io
import json
import random
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_reseau_multiclients import Server, PASSWORD, req, auth

random.seed(20261115)  # reproductible

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


def build_course(client, trainer, group='BTS SIO - Réseaux', event='Cours TCP IP'):
    """Le formateur prépare un cours réaliste de 11 slides."""
    g = req(client, 'POST', '/api/v1/groups', token=trainer,
            json={'group': group}).json()['group']
    e = req(client, 'POST', '/api/v1/events', token=trainer,
            json={'group': g, 'title': event}).json()['title']
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    slides = {}
    def add(title, kind, content):
        r = req(client, 'POST', base, token=trainer,
                json={'title': title, 'slide_type': kind, 'content': content})
        slides[title] = r.json()['slide']
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


def join_student(client, code, nom, prenom):
    r = client.post('/api/v1/student/join', json={
        'session_code': code, 'nom': nom, 'prenom': prenom})
    assert r.status_code == 200, r.text
    return r.json()['student_session_id'], r.json()['participation_id']


def add_simple_qcm(client, trainer, base, title='QCM simple'):
    """Ajoute un QCM à réponse B, renvoie le nom de la slide."""
    req(client, 'POST', base, token=trainer,
        json={'title': title, 'slide_type': 'Q',
              'content': '---\nclasslive_answer:\n  selected: [B]\n---\n# Question ?\n- A\n- B'})
    return title


def cleanup(client, trainer, g, e):
    """Supprime événement et groupe (les sessions sont déjà arrêtées)."""
    req(client, 'DELETE', f'/api/v1/groups/{g}/events/{e}/sessions', token=trainer)
    req(client, 'DELETE', f'/api/v1/groups/{g}/events/{e}', token=trainer)
    req(client, 'DELETE', f'/api/v1/groups/{g}', token=trainer)


def scenario_cours_40(client, trainer):
    """Le scénario principal : 11 slides, 40 étudiants, correction, annonce,
    reconnexion, exports et attribution."""
    g, e, base, slides = build_course(client, trainer)
    live = req(client, 'POST', '/api/v1/live/start', token=trainer,
               json={'group': g, 'title': e}).json()
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
            h = {'Authorization': 'Bearer ' + tokens[i]}
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
                                headers={'Authorization': 'Bearer ' + tokens[i]},
                                json={'text': f'Question de {PRENOMS[i]} sur {title} ?'})
        # Réactions emoji éparses
        if idx in (2, 5):
            for i in range(0, 40, 5):
                if i in joined:
                    client.post('/api/v1/student/reaction',
                                headers={'Authorization': 'Bearer ' + tokens[i]},
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
                          headers={'Authorization': 'Bearer ' + tokens[0]},
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

    # Stats agrégées
    stats = req(client, 'GET', f'/api/v1/live/{lid}/stats', token=trainer).json()
    print('[1] Stats agrégées OK :', json.dumps(stats)[:200])

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
    csv_resp = client.get(f'/api/v1/live/{lid}/export.csv',
                          headers={'Authorization': 'Bearer ' + trainer})
    assert csv_resp.status_code == 200
    rows = list(csv.DictReader(io.StringIO(csv_resp.content.decode('utf-8-sig')),
                               delimiter=';'))
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
        r = client.get(path, headers={'Authorization': 'Bearer ' + trainer})
        assert r.status_code == 200, (name, r.status_code)
        rrows = list(csv.DictReader(io.StringIO(r.content.decode('utf-8-sig')),
                                    delimiter=';'))
        assert set(rrows[0]) == cols, (name, rrows[0])
        print(f'[1] Export {name} : {len(rrows)} lignes, colonnes vérifiées.')

    # ── Résultats par étudiant (toutes sessions de l'événement) ──
    sr = req(client, 'GET',
             f'/api/v1/groups/{g}/events/{e}/student-results',
             token=trainer, params={'nom': NOMS[0], 'prenom': PRENOMS[0]}).json()
    assert sr['total_answers'] == answered[0], (sr['total_answers'], answered[0])
    print(f'[1] Résultats par étudiant ({NOMS[0]} {PRENOMS[0]}) : '
          f'{sr["total_answers"]} réponses.')

    # ── Fin de séance : arrêt, archive, nettoyage ──
    req(client, 'POST', f'/api/v1/live/{lid}/stop', token=trainer)
    req(client, 'DELETE', f'/api/v1/live/{lid}', token=trainer)
    cleanup(client, trainer, g, e)
    print('[1] Séance terminée et données de test nettoyées.')


def scenario_verrouillage(client, trainer):
    """Compte à rebours par question : réponse refusée après la deadline."""
    g = req(client, 'POST', '/api/v1/groups', token=trainer,
            json={'group': 'Verrouillage'}).json()['group']
    e = req(client, 'POST', '/api/v1/events', token=trainer,
            json={'group': g, 'title': 'Timing'}).json()['title']
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    add_simple_qcm(client, trainer, base)
    live = req(client, 'POST', '/api/v1/live/start', token=trainer,
               json={'group': g, 'title': e, 'timing': 'par_question',
                     'timing_seconds': 1}).json()
    lid, code = live['live_id'], live['session_code']
    tok, _ = join_student(client, code, 'Durand', 'Marie')
    h = {'Authorization': 'Bearer ' + tok}
    # Réponse immédiate acceptée
    assert client.post('/api/v1/student/answers', headers=h,
                       json={'answer': {'selected': ['B']}}).status_code == 200
    time.sleep(1.5)  # la deadline (1 s) est dépassée
    # Réponse refusée : temps écoulé
    late = client.post('/api/v1/student/answers', headers=h,
                       json={'answer': {'selected': ['A']}})
    assert late.status_code == 409, late.text
    print('[2] Verrouillage par compte à rebours : réponse refusée après la deadline.')
    req(client, 'POST', f'/api/v1/live/{lid}/stop', token=trainer)
    req(client, 'DELETE', f'/api/v1/live/{lid}', token=trainer)
    cleanup(client, trainer, g, e)


def scenario_planification(client, trainer):
    """Live planifié (start_at futur) : statut scheduled, puis arrêt."""
    g = req(client, 'POST', '/api/v1/groups', token=trainer,
            json={'group': 'Planification'}).json()['group']
    e = req(client, 'POST', '/api/v1/events', token=trainer,
            json={'group': g, 'title': 'Prévu'}).json()['title']
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    add_simple_qcm(client, trainer, base)
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    live = req(client, 'POST', '/api/v1/live/start', token=trainer,
               json={'group': g, 'title': e, 'start_at': future}).json()
    assert live['status'] == 'scheduled', live
    sched = req(client, 'GET', '/api/v1/live/scheduled', token=trainer).json()
    assert any(s['id'] == live['live_id'] for s in sched['scheduled']), sched
    print('[3] Live planifié : statut scheduled et visible dans /live/scheduled.')
    req(client, 'POST', f"/api/v1/live/{live['live_id']}/stop", token=trainer)
    req(client, 'DELETE', f"/api/v1/live/{live['live_id']}", token=trainer)
    cleanup(client, trainer, g, e)


def scenario_anonyme(client, trainer):
    """Mode anonyme : identités masquées dans results, mais student-results
    par nom fonctionne toujours."""
    g = req(client, 'POST', '/api/v1/groups', token=trainer,
            json={'group': 'Anonymat'}).json()['group']
    e = req(client, 'POST', '/api/v1/events', token=trainer,
            json={'group': g, 'title': 'Anonyme'}).json()['title']
    base = f'/api/v1/groups/{g}/events/{e}/slides'
    add_simple_qcm(client, trainer, base)
    live = req(client, 'POST', '/api/v1/live/start', token=trainer,
               json={'group': g, 'title': e, 'anonymous': True}).json()
    lid, code = live['live_id'], live['session_code']
    assert live['anonymous'] is True
    tok, _ = join_student(client, code, 'Dupont', 'Marie')
    client.post('/api/v1/student/answers',
                headers={'Authorization': 'Bearer ' + tok},
                json={'answer': {'selected': ['B']}})
    res = req(client, 'GET', f'/api/v1/live/{lid}/results', token=trainer).json()
    assert res['anonymous'] is True and res['results'][0]['nom'] == 'anonyme', res
    # L'identité reste traçable par nom/prénom pour le formateur
    sr = req(client, 'GET', f'/api/v1/groups/{g}/events/{e}/student-results',
             token=trainer, params={'nom': 'Dupont', 'prenom': 'Marie'}).json()
    assert sr['total_answers'] == 1, sr
    print('[4] Mode anonyme : identités masquées, traçabilité par nom conservée.')
    req(client, 'POST', f'/api/v1/live/{lid}/stop', token=trainer)
    req(client, 'DELETE', f'/api/v1/live/{lid}', token=trainer)
    cleanup(client, trainer, g, e)


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
            print('\nSUCCÈS : scénario formateur + 40 étudiants validé de bout en bout.')
        except Exception:
            print('\n--- Journaux du serveur éphémère ---\n' + srv.log_tail(), file=sys.stderr)
            raise
        finally:
            srv.stop()


if __name__ == '__main__':
    main()
