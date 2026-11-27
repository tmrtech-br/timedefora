"""Sobe o ambiente LOCAL de desenvolvimento do LocaPlay com um único comando.

    python dev.py              # prepara o que faltar e sobe banco + API + frontend
    python dev.py --demo       # idem, recriando os dados demonstrativos (SIMULADOS)
    python dev.py --setup      # só prepara (banco, dependências, .env, migrations) e sai
    python dev.py --db         # sobe SÓ o PostgreSQL (ex.: para usar HeidiSQL/pgAdmin); Ctrl+C desliga

O que ele faz, nesta ordem (cada passo é pulado se já estiver pronto):
  0. Encerra o que estiver ocupando as portas 8000 (API) e 3000 (Next), ex.: terminais esquecidos.
  1. PostgreSQL: cria um cluster próprio de dev (initdb) e o inicia na porta 5433.
     Não usa o serviço do Windows (que exige administrador). Remove trava velha (postmaster.pid).
  2. Cria os bancos `locaplay` e `locaplay_test`.
  3. Backend: cria .venv e instala requirements-dev.txt (reinstala se o arquivo mudar);
     gera backend/.env a partir do .env.example na primeira vez (chave aleatória, senha do admin aleatória).
  4. Aplica migrations e o seed básico; na primeira vez cria o superadministrador e os dados demo.
  5. Frontend: npm install (se faltar ou se package-lock mudar) e .env.local.
  6. Sobe API (8000), Next (3000) e o ConsoleAgent (se agent/config.json existir) com saída prefixada. Ctrl+C encerra tudo, banco incluído, de forma limpa.

Variáveis opcionais: LOCAPLAY_PGDATA (pasta do cluster), LOCAPLAY_PGPORT (padrão 5433), PG_BIN (pasta bin do PostgreSQL).
Só usa a biblioteca padrão do Python 3.11+. Nunca aponte para o Supabase: isto é só para desenvolvimento local.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / 'backend'
FRONTEND = ROOT / 'frontend'
AGENT = ROOT / 'agent'
WIN = os.name == 'nt'

PGDATA = Path(os.getenv('LOCAPLAY_PGDATA', str(ROOT.parent / '.pgdata-dev')))
PGPORT = int(os.getenv('LOCAPLAY_PGPORT', '5433'))
PGLOG = PGDATA.parent / f'{PGDATA.name}.log'
SEEDED_MARK = PGDATA / '.locaplay_seeded'
VENV_PY = BACKEND / '.venv' / ('Scripts/python.exe' if WIN else 'bin/python')
DB_URL = f'postgresql://postgres@localhost:{PGPORT}/locaplay'
TEST_DB_URL = f'postgresql://postgres@localhost:{PGPORT}/locaplay_test'

COLORS = {'db': '\033[36m', 'api': '\033[35m', 'web': '\033[32m', 'agt': '\033[34m', 'dev': '\033[33m'}
RESET = '\033[0m'
if WIN:
    os.system('')  # habilita cores ANSI no console do Windows
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

_print_lock = threading.Lock()
LOG_DIR = ROOT / 'logs'
_log_file = None


def _log_to_file(line: str) -> None:
    """Cópia de tudo o que aparece no terminal em logs/dev-AAAAMMDD.log (para diagnóstico depois)."""
    global _log_file
    try:
        name = LOG_DIR / time.strftime('dev-%Y%m%d.log')
        if _log_file is None or _log_file.name != str(name):
            LOG_DIR.mkdir(exist_ok=True)
            if _log_file is not None:
                _log_file.close()
            _log_file = open(name, 'a', encoding='utf-8')
        _log_file.write(f"{time.strftime('%H:%M:%S')} {line}\n")
        _log_file.flush()
    except OSError:
        pass                                   # o log em arquivo nunca derruba o ambiente


def log(msg: str, tag: str = 'dev') -> None:
    with _print_lock:
        print(f"{COLORS.get(tag, '')}[{tag}]{RESET} {msg}", flush=True)
        _log_to_file(f'[{tag}] {msg}')


def die(msg: str) -> None:
    log(f'ERRO: {msg}')
    sys.exit(1)


def run(cmd: list[str], cwd: Path | None = None, env: dict | None = None, check: bool = True,
        capture: bool = False) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=capture,
                       encoding='utf-8', errors='replace')
    if check and r.returncode != 0:
        if capture:
            sys.stderr.write((r.stdout or '') + (r.stderr or ''))
        die(f"comando falhou ({r.returncode}): {' '.join(map(str, cmd))}")
    return r


def file_hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ''


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(('127.0.0.1', port)) == 0


def port_pids(port: int) -> set[int]:
    """PIDs que estão escutando na porta (127.0.0.1, 0.0.0.0 ou ::)."""
    pids: set[int] = set()
    if WIN:
        r = subprocess.run(['netstat', '-ano', '-p', 'TCP'], capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        r6 = subprocess.run(['netstat', '-ano', '-p', 'TCPv6'], capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
        for line in (r.stdout + r6.stdout).splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[1].rsplit(':', 1)[-1] == str(port) and parts[3].upper() in ('LISTENING', 'ESCUTANDO'):
                if parts[4].isdigit() and int(parts[4]) > 0:
                    pids.add(int(parts[4]))
    elif shutil.which('lsof'):
        r = subprocess.run(['lsof', '-ti', f'tcp:{port}', '-sTCP:LISTEN'], capture_output=True, text=True)
        pids = {int(x) for x in r.stdout.split() if x.isdigit()}
    return pids


def proc_name(pid: int) -> str:
    if WIN:
        r = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'], capture_output=True,
                           text=True, encoding='utf-8', errors='replace')
        first = r.stdout.strip().split(',')[0].strip('"')
        return first if first and 'INFO' not in first.upper() else '?'
    return '?'


def kill_pid_tree(pid: int) -> None:
    if WIN:
        subprocess.run(['taskkill', '/T', '/F', '/PID', str(pid)], capture_output=True)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def free_port(port: int, label: str) -> None:
    """Encerra o que estiver escutando na porta (ex.: API/Next esquecidos em outro terminal)."""
    if not port_open(port):
        return
    pids = port_pids(port) - {os.getpid()}
    if not pids:
        die(f'a porta {port} ({label}) está em uso e não consegui identificar o processo. Feche-o manualmente.')
    for pid in pids:
        log(f'porta {port} ({label}) ocupada por {proc_name(pid)} (PID {pid}); encerrando')
        kill_pid_tree(pid)
    for _ in range(20):
        if not port_open(port):
            return
        time.sleep(0.5)
    die(f'não consegui liberar a porta {port} ({label}). Feche o processo manualmente.')


# ---------------------------------------------------------------- PostgreSQL
def find_pg_bin() -> Path:
    cands = [os.getenv('PG_BIN')] if os.getenv('PG_BIN') else []
    if WIN:
        found = glob.glob(r'C:\Program Files\PostgreSQL\*\bin')
        found.sort(key=lambda p: int(Path(p).parent.name) if Path(p).parent.name.isdigit() else 0, reverse=True)
        cands += found
    which = shutil.which('initdb')
    if which:
        cands.append(str(Path(which).parent))
    for c in cands:
        exe = Path(c) / ('initdb.exe' if WIN else 'initdb')
        if exe.exists():
            return Path(c)
    die('PostgreSQL não encontrado. Instale o PostgreSQL 15+ ou defina PG_BIN com a pasta bin.')
    raise SystemExit


def pg(bin_dir: Path, name: str) -> str:
    return str(bin_dir / (f'{name}.exe' if WIN else name))


def pid_alive(pid: int) -> bool:
    if WIN:
        r = subprocess.run(['tasklist', '/FI', f'PID eq {pid}', '/NH'], capture_output=True, text=True,
                           encoding='utf-8', errors='replace')
        return str(pid) in r.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def pg_ready(bin_dir: Path) -> bool:
    return subprocess.run([pg(bin_dir, 'pg_isready'), '-h', 'localhost', '-p', str(PGPORT), '-q']).returncode == 0


def start_postgres(bin_dir: Path) -> subprocess.Popen | None:
    if not (PGDATA / 'PG_VERSION').exists():
        log(f'criando cluster PostgreSQL de dev em {PGDATA}', 'db')
        PGDATA.mkdir(parents=True, exist_ok=True)
        run([pg(bin_dir, 'initdb'), '-D', str(PGDATA), '-U', 'postgres', '--auth=trust',
             '-E', 'UTF8', '--locale=C'], capture=True)

    if pg_ready(bin_dir):
        log(f'PostgreSQL já está rodando na porta {PGPORT} (não será desligado ao sair)', 'db')
        return None

    pidfile = PGDATA / 'postmaster.pid'
    if pidfile.exists():
        try:
            old = int(pidfile.read_text().splitlines()[0])
        except Exception:
            old = -1
        if old > 0 and pid_alive(old):
            log(f'postgres travado (PID {old}) usando {PGDATA}; encerrando', 'db')
            kill_pid_tree(old)
            time.sleep(1)
        log('removendo trava velha (postmaster.pid)', 'db')
        pidfile.unlink(missing_ok=True)

    if port_open(PGPORT):
        die(f'a porta {PGPORT} está ocupada por outro programa. Defina LOCAPLAY_PGPORT com outra porta.')

    log(f'iniciando PostgreSQL na porta {PGPORT} (log: {PGLOG})', 'db')
    logf = open(PGLOG, 'a', encoding='utf-8')
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if WIN else 0
    proc = subprocess.Popen([pg(bin_dir, 'postgres'), '-D', str(PGDATA), '-p', str(PGPORT)],
                            stdout=logf, stderr=subprocess.STDOUT, creationflags=flags,
                            start_new_session=not WIN)
    for _ in range(60):
        if pg_ready(bin_dir):
            log('PostgreSQL pronto', 'db')
            return proc
        if proc.poll() is not None:
            die(f'PostgreSQL encerrou ao iniciar. Veja {PGLOG}')
        time.sleep(0.5)
    die(f'PostgreSQL não respondeu em 30 s. Veja {PGLOG}')
    raise SystemExit


def stop_postgres(bin_dir: Path, proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    log('desligando PostgreSQL (fast shutdown)...', 'db')
    # No Windows o postgres trata CTRL_BREAK como "fast shutdown" (não depende do pg_ctl).
    proc.send_signal(signal.CTRL_BREAK_EVENT if WIN else signal.SIGINT)
    try:
        proc.wait(timeout=60)
    except subprocess.TimeoutExpired:
        log('PostgreSQL não desligou em 60 s; forçando (a próxima subida fará recuperação automática)', 'db')
        if WIN:
            subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)], capture_output=True)
        proc.kill()


def ensure_databases(bin_dir: Path) -> None:
    for db in ('locaplay', 'locaplay_test'):
        r = run([pg(bin_dir, 'psql'), '-h', 'localhost', '-p', str(PGPORT), '-U', 'postgres', '-d', 'postgres',
                 '-Atc', f"select 1 from pg_database where datname='{db}'"], capture=True)
        if r.stdout.strip() != '1':
            log(f'criando banco {db}', 'db')
            run([pg(bin_dir, 'psql'), '-h', 'localhost', '-p', str(PGPORT), '-U', 'postgres', '-d', 'postgres',
                 '-c', f'create database {db}'], capture=True)


# ---------------------------------------------------------------- Backend
def ensure_venv() -> None:
    req = BACKEND / 'requirements-dev.txt'
    mark = BACKEND / '.venv' / '.req_hash'
    if not VENV_PY.exists():
        log('criando ambiente virtual Python (backend/.venv)', 'api')
        run([sys.executable, '-m', 'venv', str(BACKEND / '.venv')])
    want = file_hash(req) + file_hash(BACKEND / 'requirements.txt')
    if not mark.exists() or mark.read_text() != want:
        log('instalando dependências do backend (pode levar alguns minutos)', 'api')
        run([str(VENV_PY), '-m', 'pip', 'install', '-q', '--disable-pip-version-check', '-r', str(req)], cwd=BACKEND)
        mark.write_text(want)


def ensure_backend_env() -> str | None:
    """Cria backend/.env na primeira vez. Devolve a senha do admin gerada (ou None se o .env já existia)."""
    env_file = BACKEND / '.env'
    if env_file.exists():
        return None
    log('gerando backend/.env a partir do .env.example', 'api')
    password = 'Dev#' + secrets.token_urlsafe(12)
    values = {
        'APP_SECRET_KEY': secrets.token_urlsafe(48),
        'DATABASE_URL': DB_URL,
        'ADMIN_EMAIL': 'admin@locaplay.local',
        'ADMIN_PASSWORD': password,
    }
    out = []
    for line in (BACKEND / '.env.example').read_text(encoding='utf-8').splitlines():
        key = line.split('=', 1)[0].strip()
        if '=' in line and not line.lstrip().startswith('#') and key in values:
            line = f'{key}={values.pop(key)}'
        out.append(line)
    out += [f'{k}={v}' for k, v in values.items()]
    out.append(f'TEST_DATABASE_URL={TEST_DB_URL}')
    env_file.write_text('\n'.join(out) + '\n', encoding='utf-8')
    return password


def read_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        v = v.strip()
        if v[:1] in ('"', "'") and v[-1:] == v[:1]:
            v = v[1:-1]
        else:
            v = v.split(' #', 1)[0].split('\t#', 1)[0].strip()
        env[k.strip()] = v
    return env


def backend_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(read_env(BACKEND / '.env'))
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PYTHONUTF8'] = '1'
    return env


def migrate_and_seed(force_demo: bool) -> None:
    env = backend_env()
    if 'localhost' not in env.get('DATABASE_URL', '') and '127.0.0.1' not in env.get('DATABASE_URL', ''):
        die('backend/.env aponta para um banco remoto. Este script só roda contra o PostgreSQL local.')
    log('aplicando migrations', 'api')
    run([str(VENV_PY), '-m', 'app.migrate'], cwd=BACKEND, env=env)
    first = not SEEDED_MARK.exists()
    args = ['--admin', '--demo', '--demo-queue'] if first else (['--demo', '--demo-queue'] if force_demo else [])
    log('seed' + (f" ({' '.join(args)})" if args else ' básico'), 'api')
    run([str(VENV_PY), '-m', 'app.seed', *args], cwd=BACKEND, env=env)
    SEEDED_MARK.write_text(time.strftime('%Y-%m-%d %H:%M:%S'))


# ---------------------------------------------------------------- Frontend
def ensure_frontend() -> None:
    npm = shutil.which('npm')
    if not npm:
        die('npm não encontrado. Instale o Node.js 20+.')
    lock = FRONTEND / 'package-lock.json'
    mark = FRONTEND / 'node_modules' / '.lock_hash'
    want = file_hash(lock) + file_hash(FRONTEND / 'package.json')
    if not (FRONTEND / 'node_modules').exists() or not mark.exists() or mark.read_text() != want:
        log('instalando dependências do frontend (npm install)', 'web')
        run([npm, 'install', '--no-audit', '--no-fund'], cwd=FRONTEND)
        mark.write_text(want)
    if not (FRONTEND / '.env.local').exists():
        shutil.copy(FRONTEND / '.env.example', FRONTEND / '.env.local')
        log('criado frontend/.env.local', 'web')


# ---------------------------------------------------------------- Processos
def pump(proc: subprocess.Popen, tag: str) -> None:
    assert proc.stdout
    for line in proc.stdout:
        log(line.rstrip(), tag)


def spawn(cmd: list[str], cwd: Path, env: dict, tag: str) -> subprocess.Popen:
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if WIN else 0
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         encoding='utf-8', errors='replace', creationflags=flags, start_new_session=not WIN)
    threading.Thread(target=pump, args=(p, tag), daemon=True).start()
    return p


def kill_tree(p: subprocess.Popen) -> None:
    if p.poll() is not None:
        return
    if WIN:
        subprocess.run(['taskkill', '/T', '/F', '/PID', str(p.pid)], capture_output=True)
    else:
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()


def agent_port() -> int:
    try:
        import json
        return int(json.loads((AGENT / 'config.json').read_text(encoding='utf-8')).get('listen_port', 8765))
    except Exception:
        return 8765


def main() -> None:
    ap = argparse.ArgumentParser(description='Sobe o ambiente local do LocaPlay.')
    ap.add_argument('--demo', action='store_true', help='recria os dados demonstrativos (SIMULADOS)')
    ap.add_argument('--setup', action='store_true', help='só prepara o ambiente e sai')
    ap.add_argument('--db', action='store_true', help='sobe só o PostgreSQL (para HeidiSQL/pgAdmin)')
    args = ap.parse_args()

    if sys.version_info < (3, 11):
        die('use Python 3.11 ou superior.')
    if WIN:  # Ctrl+Break também encerra de forma limpa
        def _on_break(*_):
            raise KeyboardInterrupt
        signal.signal(signal.SIGBREAK, _on_break)
    if not args.setup and not args.db:
        for port, name in ((8000, 'API'), (3000, 'frontend')):
            free_port(port, name)

    bin_dir = find_pg_bin()
    pg_proc = start_postgres(bin_dir)
    procs: list[subprocess.Popen] = []
    try:
        ensure_databases(bin_dir)
        if args.db:
            log('-' * 60)
            log(f'PostgreSQL rodando: host 127.0.0.1 · porta {PGPORT} · usuário postgres · sem senha · banco locaplay')
            log('Ctrl+C desliga o banco.')
            log('-' * 60)
            while pg_proc is None or pg_proc.poll() is None:
                time.sleep(1)
            die(f'PostgreSQL encerrou inesperadamente. Veja {PGLOG}')
        ensure_venv()
        new_password = ensure_backend_env()
        migrate_and_seed(args.demo)
        ensure_frontend()

        env = backend_env()
        if args.setup:
            log('ambiente preparado.')
            return

        procs.append(spawn([str(VENV_PY), '-m', 'uvicorn', 'app.main:app', '--reload', '--port', '8000'],
                           BACKEND, env, 'api'))
        npm = shutil.which('npm')
        procs.append(spawn([npm, 'run', 'dev'], FRONTEND, os.environ.copy(), 'web'))
        names = ['API', 'frontend']
        if (AGENT / 'config.json').exists():
            free_port(agent_port(), 'ConsoleAgent')
            aenv = os.environ.copy()
            aenv.update({'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'})
            procs.append(spawn([str(VENV_PY), '-m', 'consoleagent'], AGENT, aenv, 'agt'))
            names.append('ConsoleAgent')
        else:
            log('ConsoleAgent não iniciado: crie agent/config.json (veja agent/README.md)', 'agt')

        log('-' * 60)
        log('Site:  http://localhost:3000')
        log('API:   http://localhost:8000/docs')
        log(f"Admin: {env.get('ADMIN_EMAIL', '?')}" + (f'  senha: {new_password}' if new_password
                                                     else '  (senha em backend/.env -> ADMIN_PASSWORD)'))
        log('A primeira abertura de cada página demora (compilação do Next). Ctrl+C encerra tudo.')
        log('-' * 60)

        while True:
            for p, name in zip(procs, names):
                if p.poll() is not None:
                    die(f'{name} encerrou (código {p.returncode}). Veja as mensagens acima.')
            if pg_proc is not None and pg_proc.poll() is not None:
                die(f'PostgreSQL encerrou inesperadamente. Veja {PGLOG}')
            time.sleep(1)
    except KeyboardInterrupt:
        log('Ctrl+C recebido, encerrando...')
    finally:
        for p in procs:
            kill_tree(p)
        stop_postgres(bin_dir, pg_proc)
        log('tudo encerrado.')


if __name__ == '__main__':
    main()
