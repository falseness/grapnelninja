#!/usr/bin/env python3
"""Check the Grapple Over store kits under artifacts/release-grapple-over/ (TASK-868).

For each portal (itch, gamepix, y8, playgama) the kit needs texts.en.md,
texts.ru.md and CHECKLIST.md; the root needs README.md. The check:

- files: every required kit file exists and is not empty;
- paths: every file path named in a CHECKLIST.md or in README.md resolves to
  an existing file or directory. A path is a token starting with artifacts/ or
  tools/, or a backticked file name with an extension (png, zip, md, json, py,
  txt, log). Relative names are looked up in the portal folder (then
  recursively under it); a name with a pattern (`*`, `0N`, `01..05`) must
  match at least one file. The report this run writes (--out) counts as
  present when a document names it;
- texts: each texts.*.md names the title Grapple Over. The itch, GamePix and
  Y8 texts never mention another mode (main/chill version, their Russian
  names, Grapnel Ninja). The Playgama texts name Grapple Over before the other
  modes and call those modes extras (bonus);
- playgama form: the description and howToPlayText halves have at least 100
  characters, the story 150..900 printable ASCII characters with no em dash;
- credentials: no value from the credentials file appears in any kit file
  (the values are never printed, only the variable names).

Usage: python3 tools/check_release_kit.py [--root DIR] [--out JSON]
       [--credentials FILE]. Exit 0 when everything passes.
"""
import argparse
import glob
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORTALS = ['itch', 'gamepix', 'y8', 'playgama']
KIT_FILES = ['texts.en.md', 'texts.ru.md', 'CHECKLIST.md']
FILE_EXT = r'(?:png|zip|md|json|py|txt|log)'
REPO_PATH_RE = re.compile(r'(?<![\w/.-])((?:artifacts|tools)/[A-Za-z0-9_.*/<>-]*[A-Za-z0-9_*/])')
BACKTICK_RE = re.compile(r'`([^`\s]+\.' + FILE_EXT + r')`')
# Mentions of the other modes that single-mode texts must not carry
OTHER_MODES_RE = re.compile(
    r'main version|chill version|Grapnel Ninja|основн\w* режим|спокойн\w* режим|'
    r"[`'\"](?:bad|classic)[`'\"]",
    re.IGNORECASE)
EXTRA_RE = re.compile(r'bonus|extra|бонус', re.IGNORECASE)


def read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def is_pattern(path):
    return '*' in path or '0N' in path or '..0' in path


def to_glob(path):
    path = re.sub(r'0(\d)\.\.0(\d)', lambda m: '0[%s-%s]' % (m.group(1), m.group(2)), path)
    return path.replace('0N', '0[0-9]')


def resolve(token, base, out=None):
    """Return the list of existing paths a referenced token stands for."""
    if out and os.path.abspath(os.path.join(REPO, token)) == os.path.abspath(out):
        return [os.path.relpath(out, REPO)]
    candidates = [os.path.join(REPO, token), os.path.join(base, token)]
    if not os.path.isabs(token) and '/' not in token:
        candidates.append(os.path.join(base, '**', token))
    found = []
    for cand in candidates:
        if is_pattern(cand) or '**' in cand:
            found += sorted(glob.glob(to_glob(cand), recursive=True))
        elif os.path.exists(cand):
            found.append(cand)
        if found:
            break
    return [os.path.relpath(f, REPO) for f in found]


def referenced_paths(text):
    tokens = []
    for m in REPO_PATH_RE.finditer(text):
        tokens.append(m.group(1).rstrip('.'))
    for m in BACKTICK_RE.finditer(text):
        tokens.append(m.group(1))
    seen, out = set(), []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def section(text, heading):
    """Body of the '## heading...' section (up to the next ## heading)."""
    m = re.search(r'^## ' + re.escape(heading) + r'[^\n]*\n(.*?)(?=^## |\Z)', text, re.M | re.S)
    return m.group(1).strip() if m else ''


def credential_values(path):
    values = {}
    if not path or not os.path.exists(path):
        return values
    for line in read(path).splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        name, value = line.split('=', 1)
        name = name.replace('export ', '').strip()
        value = value.strip().strip('"').strip("'")
        if len(value) >= 6:
            values[name] = value
    return values


def check(root, credentials, out=None):
    result = {'root': os.path.relpath(root, REPO), 'files': [], 'paths': [], 'texts': [],
              'playgama_form': {}, 'credentials': {}}
    kit_files = [os.path.join(root, 'README.md')] + [
        os.path.join(root, p, f) for p in PORTALS for f in KIT_FILES]
    for f in kit_files:
        ok = os.path.isfile(f) and os.path.getsize(f) > 0
        result['files'].append({'file': os.path.relpath(f, REPO), 'exists': os.path.isfile(f),
                                'bytes': os.path.getsize(f) if os.path.isfile(f) else 0, 'ok': ok})

    # Every path named in a checklist (and the README) exists
    docs = [(os.path.join(root, 'README.md'), root)] + [
        (os.path.join(root, p, 'CHECKLIST.md'), os.path.join(root, p)) for p in PORTALS]
    for doc, base in docs:
        if not os.path.isfile(doc):
            continue
        for token in referenced_paths(read(doc)):
            found = resolve(token, base, out)
            self_ref = bool(out) and found == [os.path.relpath(out, REPO)]
            result['paths'].append({'doc': os.path.relpath(doc, REPO), 'path': token,
                                    'pattern': is_pattern(token), 'resolved': found[:12],
                                    'matches': len(found), 'ok': bool(found),
                                    **({'note': 'the report this run writes'} if self_ref else {})})

    # Title and mode mentions
    for portal in PORTALS:
        for name in ['texts.en.md', 'texts.ru.md']:
            path = os.path.join(root, portal, name)
            if not os.path.isfile(path):
                continue
            text = read(path)
            lines = text.splitlines()
            other = [{'line': i + 1, 'match': m.group(0), 'text': l.strip()[:160]}
                     for i, l in enumerate(lines) for m in OTHER_MODES_RE.finditer(l)]
            entry = {'file': os.path.relpath(path, REPO), 'portal': portal,
                     'grapple_over_count': text.count('Grapple Over'),
                     'title_line': bool(re.search(r'^## (?:Title|Название|title)\s*\n+Grapple Over\s*$', text, re.M)),
                     'other_mode_hits': other}
            if portal == 'playgama':
                first_go = text.find('Grapple Over')
                first_other = min([m.start() for m in OTHER_MODES_RE.finditer(text)] or [len(text)])
                entry['grapple_over_first'] = 0 <= first_go < first_other
                entry['other_modes_present'] = bool(other)
                entry['extras_hits'] = [{'line': i + 1, 'text': l.strip()[:160]}
                                        for i, l in enumerate(lines)
                                        if EXTRA_RE.search(l) and OTHER_MODES_RE.search(l)]
                title_ok = entry['grapple_over_count'] > 0 and (
                    entry['title_line'] or name == 'texts.ru.md')
                entry['ok'] = (title_ok and entry['grapple_over_first'] and
                               entry['other_modes_present'] and bool(entry['extras_hits']))
            else:
                entry['ok'] = entry['title_line'] and not other
            result['texts'].append(entry)

    # Playgama form limits
    en_path = os.path.join(root, 'playgama', 'texts.en.md')
    ru_path = os.path.join(root, 'playgama', 'texts.ru.md')
    if os.path.isfile(en_path) and os.path.isfile(ru_path):
        en = read(en_path)
        ru = read(ru_path)
        story = section(en, 'story')
        form = {
            'description_en_chars': len(section(en, 'description')),
            'description_ru_chars': len(section(ru, 'description')),
            'howto_en_chars': len(section(en, 'howToPlayText')),
            'howto_ru_chars': len(section(ru, 'howToPlayText')),
            'story_chars': len(story),
            'story_ascii': all(32 <= ord(c) < 127 or c == '\n' for c in story),
            'story_no_em_dash': '—' not in story,
            'title_value': section(en, 'title'),
        }
        form['ok'] = (min(form['description_en_chars'], form['description_ru_chars'],
                          form['howto_en_chars'], form['howto_ru_chars']) >= 100 and
                      150 <= form['story_chars'] <= 900 and form['story_ascii'] and
                      form['story_no_em_dash'] and form['title_value'] == 'Grapple Over')
        result['playgama_form'] = form

    # No credential value in any kit file (names only in the output)
    values = credential_values(credentials)
    hits = []
    for f in kit_files:
        if os.path.isfile(f):
            text = read(f)
            hits += [{'file': os.path.relpath(f, REPO), 'variable': n}
                     for n, v in values.items() if v in text]
    result['credentials'] = {'file_read': bool(values), 'variables_checked': sorted(values),
                             'hits': hits, 'ok': bool(values) and not hits}

    result['summary'] = {
        'files_ok': all(e['ok'] for e in result['files']),
        'files': len(result['files']),
        'paths_checked': len(result['paths']),
        'paths_missing': [e['path'] for e in result['paths'] if not e['ok']],
        'paths_ok': all(e['ok'] for e in result['paths']) and bool(result['paths']),
        'texts_ok': all(e['ok'] for e in result['texts']) and len(result['texts']) == 8,
        'playgama_form_ok': result['playgama_form'].get('ok', False),
        'credentials_ok': result['credentials']['ok'],
    }
    s = result['summary']
    result['all_ok'] = all([s['files_ok'], s['paths_ok'], s['texts_ok'],
                            s['playgama_form_ok'], s['credentials_ok']])
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--root', default=os.path.join(REPO, 'artifacts', 'release-grapple-over'))
    ap.add_argument('--out', default=None)
    ap.add_argument('--credentials', default='/root/credentials/grapnelninja/credentials.env')
    args = ap.parse_args()
    result = check(os.path.abspath(args.root), args.credentials, args.out)
    text = json.dumps(result, indent=1, ensure_ascii=False)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, 'w', encoding='utf-8') as f:
            f.write(text + '\n')
    print(json.dumps({'summary': result['summary'], 'all_ok': result['all_ok']}, indent=1,
                     ensure_ascii=False))
    return 0 if result['all_ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
