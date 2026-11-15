#!/usr/bin/env python3
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

AUTO_START = '<!-- AUTO-LINKS:START -->'
AUTO_END = '<!-- AUTO-LINKS:END -->'
IGNORE_ENTRY = '.cursor/task.md'
DEFAULT_CONFIG = {
    'jira_base_url': 'https://YOUR-COMPANY.atlassian.net',
    'ticket_regex': r'([A-Z][A-Z0-9]+-[0-9]+)',
    'worktree_parent': '../{repo}-worktrees',
}


def run(cmd, cwd=None, check=True):
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or 'command failed')
    return proc.stdout.strip(), proc.returncode


def install_dir():
    return Path(__file__).resolve().parent


def load_config():
    path = install_dir() / 'task-workspace.json'
    cfg = dict(DEFAULT_CONFIG)
    if path.exists():
        try:
            cfg.update(json.loads(path.read_text()))
        except Exception as exc:
            raise RuntimeError(f'Invalid global config {path}: {exc}')
    return cfg


def git_root(cwd=None):
    out, rc = run(['git', 'rev-parse', '--show-toplevel'], cwd=cwd, check=False)
    if rc != 0:
        raise RuntimeError('Run ctask from inside a Git repository.')
    return Path(out).resolve()


def current_branch(root):
    out, _ = run(['git', 'branch', '--show-current'], cwd=root, check=False)
    return out


def origin_url(root):
    out, _ = run(['git', 'config', '--get', 'remote.origin.url'], cwd=root, check=False)
    return out


def normalize_git_url(remote):
    if not remote:
        return ''
    value = remote.strip()
    if value.startswith('git@') and ':' in value:
        host_path = value[4:]
        host, path = host_path.split(':', 1)
        value = f'https://{host}/{path}'
    elif value.startswith('ssh://git@'):
        rest = value[len('ssh://git@'):]
        host, _, path = rest.partition('/')
        value = f'https://{host}/{path}'
    if value.endswith('.git'):
        value = value[:-4]
    return value


def ticket_from_text(text, regex):
    if not text:
        return ''
    match = re.search(regex, text)
    return match.group(1) if match else ''




def text_has_ticket(text, ticket):
    if not text or not ticket:
        return False
    pattern = rf'(?i)(?<![A-Z0-9]){re.escape(ticket)}(?![A-Z0-9])'
    return re.search(pattern, text) is not None


def local_branches(root):
    out, _ = run([
        'git', 'for-each-ref', '--sort=-committerdate',
        '--format=%(refname:short)', 'refs/heads/'
    ], cwd=root, check=False)
    return [line.strip() for line in out.splitlines() if line.strip()]


def remote_branches(root):
    out, _ = run([
        'git', 'for-each-ref', '--sort=-committerdate',
        '--format=%(refname:short)', 'refs/remotes/'
    ], cwd=root, check=False)
    return [
        line.strip() for line in out.splitlines()
        if line.strip() and not line.strip().endswith('/HEAD')
    ]


def branch_basename(branch):
    return branch.split('/', 1)[-1] if '/' in branch else branch


def first_matching_branch(branches, ticket, workspace_id=None):
    workspace_id = workspace_id or ticket
    exact = [b for b in branches if branch_basename(b).lower() == workspace_id.lower()]
    if exact:
        return exact[0]

    # With a suffix, never silently adopt another workspace for the same Jira ticket.
    if workspace_id.lower() != ticket.lower():
        token_matches = [
            b for b in branches
            if branch_basename(b).lower().startswith(workspace_id.lower())
        ]
        return token_matches[0] if token_matches else ''

    # Backward compatibility for older branches such as feature/MB-1842-something.
    matches = [b for b in branches if text_has_ticket(b, ticket)]
    if not matches:
        return ''
    preferred = [b for b in matches if branch_basename(b).upper().startswith(ticket.upper())]
    return (preferred or matches)[0]


def matching_open_pr(root, ticket, workspace_id=None):
    if shutil.which('gh') is None:
        return None
    raw = gh_value(root, [
        'pr', 'list', '--state', 'open', '--limit', '200',
        '--json', 'number,title,url,headRefName,body'
    ])
    if not raw:
        return None
    try:
        prs = json.loads(raw)
    except Exception:
        return None
    workspace_id = workspace_id or ticket
    candidates = []
    for pr in prs if isinstance(prs, list) else []:
        head = str(pr.get('headRefName') or '')
        title = str(pr.get('title') or '')
        body = str(pr.get('body') or '')

        if workspace_id.lower() != ticket.lower():
            # A suffixed workspace must match that specific branch/task identity.
            if workspace_id.lower() in head.lower():
                score = 0
            elif workspace_id.lower() in title.lower():
                score = 1
            elif workspace_id.lower() in body.lower():
                score = 2
            else:
                continue
        else:
            if head.lower() == workspace_id.lower():
                score = 0
            elif text_has_ticket(head, ticket):
                score = 1
            elif text_has_ticket(title, ticket):
                score = 2
            elif text_has_ticket(body, ticket):
                score = 3
            else:
                continue
        candidates.append((score, pr))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def fetch_origin(root):
    if not origin_url(root):
        return
    run(['git', 'fetch', 'origin', '--prune'], cwd=root, check=False)


def resolve_start_point(root, requested):
    """A local branch, or origin/<name>, that --branch names."""
    if requested in local_branches(root):
        return requested
    if '/' in requested and requested.split('/', 1)[0] in {'origin', 'upstream'}:
        remote_requested = requested
    else:
        remote_requested = f'origin/{requested}'
    if remote_requested in remote_branches(root):
        return remote_requested
    raise RuntimeError(f'Branch not found locally or remotely: {requested}')


def add_worktree_from_start(root, path, workspace_id, start_point):
    """Check out a new branch named like the folder, starting at start_point.

    If start_point is already that branch, check it out instead of creating a duplicate.
    """
    start_name = branch_basename(start_point)
    if start_name.lower() == workspace_id.lower():
        if start_name in local_branches(root):
            run(['git', 'worktree', 'add', str(path), start_name], cwd=root)
            return start_name, 'existing local branch'
        return add_worktree_for_remote(root, path, start_point), 'existing remote branch'
    if workspace_id in local_branches(root):
        raise RuntimeError(
            f'Branch {workspace_id} already exists. '
            f'Omit --branch to resume it, or delete it before starting from {start_point}.'
        )
    # Do not track the start point. The new ticket branch must not push onto the base.
    run([
        'git', 'worktree', 'add', '--no-track', '-b', workspace_id,
        str(path), start_point,
    ], cwd=root)
    return workspace_id, f'new branch from {start_point}'


def add_worktree_for_remote(root, path, remote_branch):
    if '/' not in remote_branch:
        raise RuntimeError(f'Invalid remote branch: {remote_branch}')
    _remote, local_branch = remote_branch.split('/', 1)
    if local_branch in local_branches(root):
        run(['git', 'worktree', 'add', str(path), local_branch], cwd=root)
    else:
        run(['git', 'worktree', 'add', '--track', '-b', local_branch, str(path), remote_branch], cwd=root)
    return local_branch


def add_worktree_for_pr(root, path, pr, ticket):
    number = pr.get('number')
    head = str(pr.get('headRefName') or '').strip()
    if not number:
        raise RuntimeError('Matching GitHub PR has no PR number.')
    local_branch = head or f'pr-{number}-{ticket.lower()}'
    if local_branch in local_branches(root):
        run(['git', 'worktree', 'add', str(path), local_branch], cwd=root)
        return local_branch
    # GitHub exposes pull/<number>/head even for PRs opened from forks, so this
    # does not require adding the contributor fork as a permanent remote.
    _, rc = run([
        'git', 'fetch', 'origin',
        f'pull/{number}/head:refs/heads/{local_branch}'
    ], cwd=root, check=False)
    if rc != 0:
        raise RuntimeError(f'Found PR #{number}, but could not fetch its head branch.')
    run(['git', 'worktree', 'add', str(path), local_branch], cwd=root)
    return local_branch


def task_path(root):
    return root / '.cursor' / 'task.md'


def read_task(root):
    path = task_path(root)
    return path.read_text() if path.exists() else ''


def task_ticket(root, cfg):
    content = read_task(root)
    if content:
        first = content.splitlines()[0] if content.splitlines() else ''
        ticket = ticket_from_text(first, cfg['ticket_regex'])
        if ticket:
            return ticket
    return ticket_from_text(current_branch(root), cfg['ticket_regex'])


def slugify(text):
    value = re.sub(r'[^a-zA-Z0-9]+', '-', text.strip()).strip('-').lower()
    return value[:60]


def ensure_task(root, ticket, title='', workspace_id=None):
    path = task_path(root)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    workspace_id = workspace_id or ticket
    heading = f'# {workspace_id}' + (f' - {title}' if title else '')
    path.write_text(
        f'''{heading}\n\n{AUTO_START}\n## Links\n- Jira: pending\n- Repository: pending\n- Branch: pending\n- PR: pending\n- CI: pending\n{AUTO_END}\n\n## Current State\nStarting work.\n\n## Next Action\nReview the ticket requirements and existing implementation.\n\n## Waiting On\nNothing.\n\n## Key Decisions\nNone yet.\n'''
    )
    return path


def append_line_once(path, line, heading=None):
    existing = path.read_text() if path.exists() else ''
    lines = [x.strip() for x in existing.splitlines()]
    if line in lines:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as f:
        if existing and not existing.endswith('\n'):
            f.write('\n')
        if heading:
            if existing and not existing.endswith('\n\n'):
                f.write('\n')
            f.write(heading.rstrip() + '\n')
        f.write(line + '\n')
    return True


def parse_worktrees(root):
    out, _ = run(['git', 'worktree', 'list', '--porcelain'], cwd=root)
    entries = []
    current = {}
    for line in out.splitlines() + ['']:
        if not line.strip():
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(' ')
        current[key] = value
    return entries


def main_worktree(root):
    entries = parse_worktrees(root)
    if not entries:
        return root
    return Path(entries[0]['worktree']).resolve()


def ensure_ignore(root):
    main = main_worktree(root)
    changed = append_line_once(main / '.gitignore', IGNORE_ENTRY, '# Cursor ticket workspace')

    common_dir_raw, _ = run(['git', 'rev-parse', '--git-common-dir'], cwd=root)
    common_dir = Path(common_dir_raw)
    if not common_dir.is_absolute():
        common_dir = (root / common_dir).resolve()
    append_line_once(common_dir / 'info' / 'exclude', IGNORE_ENTRY, '# Cursor ticket workspace')
    return changed, main / '.gitignore'


def gh_value(root, args):
    if shutil.which('gh') is None:
        return ''
    out, rc = run(['gh', *args], cwd=root, check=False)
    return out.strip() if rc == 0 else ''


def build_links(root, cfg, ticket):
    branch = current_branch(root)
    repo_url = normalize_git_url(origin_url(root))
    jira_base = cfg.get('jira_base_url', '').rstrip('/')
    jira_url = f'{jira_base}/browse/{ticket}' if jira_base and ticket else ''
    pr_url = gh_value(root, ['pr', 'view', '--json', 'url', '--jq', '.url'])
    if not pr_url and ticket:
        pr = matching_open_pr(root, ticket)
        pr_url = str(pr.get('url') or '') if pr else ''
    ci_url = gh_value(root, ['run', 'list', '--branch', branch, '--limit', '1', '--json', 'url', '--jq', '.[0].url']) if branch else ''
    if not ci_url and repo_url and 'github.com/' in repo_url:
        ci_url = f'{repo_url}/actions'
    branch_url = ''
    if repo_url and branch and 'github.com/' in repo_url:
        branch_url = f'{repo_url}/tree/{urllib.parse.quote(branch, safe="")}'
    return {
        'Jira': jira_url or 'pending',
        'Repository': repo_url or 'pending',
        'Branch': f'[{branch}]({branch_url})' if branch_url else (branch or 'pending'),
        'PR': pr_url or 'pending',
        'CI': ci_url or 'pending',
    }


def replace_auto_links(content, links):
    block = AUTO_START + '\n## Links\n' + '\n'.join(f'- {k}: {v}' for k, v in links.items()) + '\n' + AUTO_END
    if AUTO_START in content and AUTO_END in content:
        pattern = re.escape(AUTO_START) + r'.*?' + re.escape(AUTO_END)
        return re.sub(pattern, block, content, flags=re.S)
    return content.rstrip() + '\n\n' + block + '\n'


def sync_task(root, quiet=False):
    cfg = load_config()
    path = task_path(root)
    if not path.exists():
        return 0
    ticket = task_ticket(root, cfg)
    if not ticket:
        if not quiet:
            print('No ticket ID found in .cursor/task.md or current branch.', file=sys.stderr)
        return 1
    content = path.read_text()
    updated = replace_auto_links(content, build_links(root, cfg, ticket))
    if updated != content:
        path.write_text(updated)
    if not quiet:
        print(f'Synced {path}')
    return 0


def find_worktree(root, workspace_id):
    target = workspace_id.lower()
    for entry in parse_worktrees(root):
        path = Path(entry.get('worktree', ''))
        branch_ref = entry.get('branch', '').replace('refs/heads/', '')
        branch_name = branch_basename(branch_ref)
        if branch_name.lower() == target or path.name.lower() == target:
            return path
        task = path / '.cursor' / 'task.md'
        if task.exists():
            first = task.read_text().splitlines()[0] if task.read_text().splitlines() else ''
            heading_id = first.lstrip('#').strip().split(' - ', 1)[0].strip()
            if heading_id.lower() == target:
                return path
    return None


def open_cursor(path):
    if shutil.which('cursor'):
        subprocess.Popen(['cursor', str(path)])
        return
    if sys.platform == 'darwin':
        subprocess.Popen(['open', '-a', 'Cursor', str(path)])
        return
    if shutil.which('xdg-open'):
        subprocess.Popen(['xdg-open', str(path)])
        return
    print(f'Open this folder in Cursor: {path}')


def cmd_start(args):
    root = git_root()
    cfg = load_config()
    ticket = args.ticket.upper()
    if not re.fullmatch(cfg['ticket_regex'], ticket):
        raise RuntimeError(f'Ticket {ticket!r} does not match configured ticket_regex.')

    suffix = slugify(args.suffix or '')
    workspace_id = ticket + (f'-{suffix}' if suffix else '')

    ignore_changed, ignore_path = ensure_ignore(root)

    # If this exact workspace already exists, `start` behaves like `open`.
    existing = find_worktree(root, workspace_id)
    if existing:
        ensure_task(existing, ticket, args.title or '', workspace_id=workspace_id)
        sync_task(existing, quiet=True)
        print(f'Ready: {workspace_id}')
        print(f'Jira: {ticket}')
        print(f'Worktree: {existing}')
        print(f'Branch: {current_branch(existing)}')
        print('Source: existing worktree')
        if ignore_changed:
            print(f'Added {IGNORE_ENTRY} to {ignore_path} (commit that .gitignore change once).')
        if not args.no_open:
            open_cursor(existing)
        return

    main = main_worktree(root)
    repo_name = main.name
    parent_tpl = cfg.get('worktree_parent', '../{repo}-worktrees')
    parent = Path(parent_tpl.format(repo=repo_name))
    if not parent.is_absolute():
        parent = (main / parent).resolve()
    path = (parent / workspace_id).resolve()
    if path.exists():
        raise RuntimeError(f'Worktree path already exists but is not registered with Git: {path}')
    parent.mkdir(parents=True, exist_ok=True)

    # Refresh origin so an existing remote branch/PR can be resumed on a new machine.
    fetch_origin(root)

    selected_branch = ''
    source = ''

    # --branch is the start point. The worktree branch matches the folder name.
    if args.branch:
        start_point = resolve_start_point(root, args.branch)
        selected_branch, source = add_worktree_from_start(root, path, workspace_id, start_point)
    else:
        local = first_matching_branch(local_branches(root), ticket, workspace_id)
        if local:
            run(['git', 'worktree', 'add', str(path), local], cwd=root)
            selected_branch = local
            source = 'existing local branch'
        else:
            remote = first_matching_branch(remote_branches(root), ticket, workspace_id)
            if remote:
                selected_branch = add_worktree_for_remote(root, path, remote)
                source = 'existing remote branch'
            else:
                pr = matching_open_pr(root, ticket, workspace_id)
                if pr:
                    selected_branch = add_worktree_for_pr(root, path, pr, ticket)
                    source = f'existing GitHub PR #{pr.get("number")}'
                    if not args.title:
                        args.title = str(pr.get('title') or '')
                else:
                    # New branches intentionally equal the workspace identity:
                    # MB-1842 or MB-1842-backend. No feature/ prefix.
                    selected_branch = workspace_id
                    run(['git', 'worktree', 'add', '-b', selected_branch, str(path)], cwd=root)
                    source = 'new branch'

    ensure_task(path, ticket, args.title or '', workspace_id=workspace_id)
    sync_task(path, quiet=True)
    print(f'Ready: {workspace_id}')
    print(f'Jira: {ticket}')
    print(f'Worktree: {path}')
    print(f'Branch: {selected_branch}')
    print(f'Source: {source}')
    if ignore_changed:
        print(f'Added {IGNORE_ENTRY} to {ignore_path} (commit that .gitignore change once).')
    if not args.no_open:
        open_cursor(path)


def cmd_sync(args):
    root = git_root()
    rc = sync_task(root, quiet=args.quiet)
    if rc:
        raise SystemExit(rc)


def cmd_open(args):
    root = git_root()
    path = find_worktree(root, args.ticket.upper())
    if not path:
        raise RuntimeError(f'No worktree found for {args.ticket.upper()}')
    open_cursor(path)
    print(path)


def extract_link(task_text, label):
    match = re.search(rf'^- {re.escape(label)}:\s*(.+)$', task_text, flags=re.M)
    if not match:
        return ''
    value = match.group(1).strip()
    md = re.fullmatch(r'\[[^\]]+\]\((https?://[^)]+)\)', value)
    if md:
        return md.group(1)
    return value if value.startswith(('http://', 'https://')) else ''


def open_url(url):
    if not url:
        raise RuntimeError('Link not available yet. Run ctask sync first.')
    if sys.platform == 'darwin':
        subprocess.Popen(['open', url])
    elif shutil.which('xdg-open'):
        subprocess.Popen(['xdg-open', url])
    else:
        print(url)


def cmd_open_link(args):
    root = git_root()
    sync_task(root, quiet=True)
    mapping = {'jira': 'Jira', 'repo': 'Repository', 'branch': 'Branch', 'pr': 'PR', 'ci': 'CI'}
    label = mapping[args.kind]
    url = extract_link(read_task(root), label)
    open_url(url)
    print(url)


def section_value(text, heading):
    pattern = rf'^## {re.escape(heading)}\s*\n(.*?)(?=\n## |\Z)'
    match = re.search(pattern, text, flags=re.M | re.S)
    if not match:
        return ''
    return ' '.join(line.strip() for line in match.group(1).strip().splitlines() if line.strip())


def cmd_status(args):
    root = git_root()
    cfg = load_config()
    rows = []
    for entry in parse_worktrees(root):
        path = Path(entry.get('worktree', ''))
        task = path / '.cursor' / 'task.md'
        branch = entry.get('branch', '').replace('refs/heads/', '')
        if not task.exists():
            continue
        if args.refresh:
            sync_task(path, quiet=True)
        text = task.read_text()
        ticket = ticket_from_text(branch, cfg['ticket_regex']) or ticket_from_text(text.splitlines()[0], cfg['ticket_regex'])
        rows.append((ticket or '-', branch or '-', section_value(text, 'Current State') or '-', section_value(text, 'Next Action') or '-', section_value(text, 'Waiting On') or '-', str(path)))
    if not rows:
        print('No active ctask worktrees found.')
        return
    headers = ('TICKET', 'BRANCH', 'STATE', 'NEXT', 'WAITING', 'PATH')
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = min(max(widths[i], len(cell)), 40)
    def trim(s, w):
        return s if len(s) <= w else s[:w-1] + '...'
    print('  '.join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    print('  '.join('-' * widths[i] for i in range(len(headers))))
    for row in rows:
        print('  '.join(trim(row[i], widths[i]).ljust(widths[i]) for i in range(len(row))))


def cmd_close(args):
    root = git_root()
    ticket = args.ticket.upper()
    path = find_worktree(root, ticket)
    if not path:
        raise RuntimeError(f'No worktree found for {ticket}')
    dirty, _ = run(['git', 'status', '--porcelain'], cwd=path, check=False)
    if dirty and not args.force:
        raise RuntimeError('Worktree has uncommitted changes. Commit/stash them or use --force.')
    merged = False
    if shutil.which('gh'):
        merged_at = gh_value(path, ['pr', 'view', '--json', 'mergedAt', '--jq', '.mergedAt'])
        merged = bool(merged_at and merged_at != 'null')
    if not merged and not args.force:
        raise RuntimeError('PR is not confirmed merged. Merge it first or use --force.')
    branch = current_branch(path)
    cmd = ['git', 'worktree', 'remove']
    if args.force:
        cmd.append('--force')
    cmd.append(str(path))
    run(cmd, cwd=root)
    print(f'Removed worktree: {path}')
    if args.delete_branch and branch:
        _, rc = run(['git', 'branch', '-d', branch], cwd=root, check=False)
        if rc != 0:
            print(f'Branch not deleted automatically: {branch}', file=sys.stderr)


def root_from_hook(payload):
    candidates = []
    if payload.get('cwd'):
        candidates.append(payload['cwd'])
    tool_input = payload.get('tool_input')
    if isinstance(tool_input, dict) and tool_input.get('working_directory'):
        candidates.append(tool_input['working_directory'])
    candidates.extend(payload.get('workspace_roots') or [])

    first_git = None
    for value in candidates:
        try:
            root = git_root(value)
        except Exception:
            continue
        if first_git is None:
            first_git = root
        if task_path(root).exists():
            return root
    return first_git


def cmd_hook(_args):
    try:
        payload = json.loads(sys.stdin.read() or '{}')
    except Exception:
        print('{}')
        return
    root = root_from_hook(payload)
    if not root or not task_path(root).exists():
        print('{}')
        return

    event = payload.get('hook_event_name', '')
    if event in {'workspaceOpen', 'sessionStart', 'afterShellExecution', 'stop'}:
        try:
            sync_task(root, quiet=True)
        except Exception:
            pass

    if event == 'sessionStart':
        content = read_task(root)
        context = (
            'ACTIVE TICKET WORKSPACE CONTEXT\n\n'
            'Use the following .cursor/task.md as the current ticket checkpoint. '
            'Respect Key Decisions. Never edit the AUTO-LINKS block manually. '
            'Keep Current State, Next Action, and Waiting On concise and current.\n\n'
            + content
        )
        print(json.dumps({'additional_context': context}))
        return

    if event == 'stop' and payload.get('status') == 'completed':
        message = (
            'Before finishing, checkpoint this ticket in .cursor/task.md. '
            'Update only Current State, Next Action, and Waiting On. '
            'Update Key Decisions only if a meaningful durable decision was made. '
            'Do not modify anything between AUTO-LINKS:START and AUTO-LINKS:END. '
            'Keep it concise. If already accurate, make no change.'
        )
        print(json.dumps({'followup_message': message}))
        return

    print('{}')


def build_parser():
    parser = argparse.ArgumentParser(description='Cursor ticket workspace helper')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('start', help='Open/resume an existing ticket or create a new ticket worktree')
    p.add_argument('ticket')
    p.add_argument('title', nargs='?', default='')
    p.add_argument('--branch', help='Start point for a new branch named like the workspace folder')
    p.add_argument('--suffix', help='Optional workspace suffix, e.g. backend -> MB-1842-backend')
    p.add_argument('--no-open', action='store_true')
    p.set_defaults(func=cmd_start)

    p = sub.add_parser('sync', help='Refresh task links in the current worktree')
    p.add_argument('--quiet', action='store_true')
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser('open', help='Open an existing ticket worktree in Cursor')
    p.add_argument('ticket')
    p.set_defaults(func=cmd_open)

    p = sub.add_parser('open-link', help='Open a link from the current task')
    p.add_argument('kind', choices=['jira', 'repo', 'branch', 'pr', 'ci'])
    p.set_defaults(func=cmd_open_link)

    p = sub.add_parser('status', help='Show active ticket worktrees')
    p.add_argument('--refresh', action='store_true')
    p.set_defaults(func=cmd_status)

    p = sub.add_parser('close', help='Remove a completed ticket worktree')
    p.add_argument('ticket')
    p.add_argument('--force', action='store_true')
    p.add_argument('--delete-branch', action='store_true')
    p.set_defaults(func=cmd_close)

    p = sub.add_parser('hook', help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_hook)
    return parser


def main():
    try:
        args = build_parser().parse_args()
        args.func(args)
    except RuntimeError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
