"""Scan reachable Git blobs and the index without emitting contents or secret paths.

A heuristic audit is not proof that no secret exists. Review findings privately;
never paste candidate credentials into logs, issues, or pull requests.
"""
import ast
import json
import re
import subprocess
import sys


def git(*args):
    return subprocess.check_output(['git', *args])


SENSITIVE_PATH = re.compile(
    r'(?:\.session(?:$|[.-])|(?:^|/)\.env(?:$|\.)|(?:^|/)(?:config\.local|credentials|secrets)\.'
    r'|(?:history|sync_state)\.json$|(?:^|/)(?:downloads|media|\.venv|venv|__pycache__)/'
    r'|\.(?:mp4|mkv|mov|jpg|jpeg|png|mp3|sqlite|db|pem|key)$)', re.I)
PATTERNS = {
    'api-hash-literal': re.compile(r'(?i)(?:api_hash|api.?hash)\s*[=:]\s*["\x27][0-9a-f]{32}["\x27]'),
    'phone-literal': re.compile(r'["\x27]\+[1-9][0-9]{9,14}["\x27]'),
    'api-id-literal': re.compile(r'(?i)api_id\s*=\s*[1-9][0-9]{4,}'),
    'private-key': re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----'),
    'access-token': re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{30,}|[0-9]{8,12}:[A-Za-z0-9_-]{30,})'),
    'possible-string-session': re.compile(r'["\x27]1[A-Za-z0-9_+/=-]{250,}["\x27]'),
}


def content_findings(data):
    text = data.decode('utf-8', errors='replace')
    # Historical UI examples are public placeholders, not account data.
    text = text.replace('"+1234567890"', '"example-phone"')
    found = [kind for kind, pattern in PATTERNS.items() if pattern.search(text)]
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return found
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str) or not value.value:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            name = target.id if isinstance(target, ast.Name) else ''
            if name.lower() in {'api_hash','phone','password','otp','auth_token','session_string'}:
                if not value.value.lower().startswith(('synthetic', 'example', 'dummy')):
                    found.append('hardcoded-authentication-value')
    return sorted(set(found))


def audit():
    findings = []
    blobs = set()
    for row in git('rev-list','--objects','--all').decode().splitlines():
        parts = row.split(' ',1)
        if len(parts) != 2:
            continue
        oid, path = parts
        if git('cat-file','-t',oid).strip() != b'blob':
            continue
        if SENSITIVE_PATH.search(path):
            findings.append({'object':oid,'reason':'sensitive-history-path'})
        if oid not in blobs:
            blobs.add(oid)
            for reason in content_findings(git('cat-file','blob',oid)):
                findings.append({'object':oid,'reason':reason})
    entries = git('ls-files','--stage','-z').decode().split('\0')
    index_files = 0
    for entry in filter(None,entries):
        metadata,path = entry.split('\t',1)
        oid = metadata.split()[1]
        index_files += 1
        if SENSITIVE_PATH.search(path):
            findings.append({'object':oid,'reason':'sensitive-index-path'})
        for reason in content_findings(git('cat-file','blob',oid)):
            findings.append({'object':oid,'reason':'index-'+reason})
    print(json.dumps({'reachable_commits':len(git('rev-list','--all').splitlines()),
                      'unique_history_blobs':len(blobs),'index_files':index_files,
                      'findings':findings},indent=2))
    return bool(findings)


if __name__ == '__main__':
    sys.exit(audit())
