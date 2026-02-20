"""
PLM Explorer — Rutas Flask para el explorador de archivos PDM
Añadir a plm_module.py o registrar como blueprint adicional
"""

import os
import sys
import json
import subprocess
import sqlite3
import hashlib
import shutil
from datetime import datetime
from flask import Blueprint, render_template, request, jsonify, send_file

plm_explorer = Blueprint('plm_explorer', __name__)

DB = os.path.join(os.path.dirname(__file__), 'crm.db')
VAULT_DIR = os.path.join(os.path.dirname(__file__), 'plm_vault')
os.makedirs(VAULT_DIR, exist_ok=True)

# Extensiones CAD reconocidas
EXT_CAD = {
    '.sldprt': ('pieza',       'solidworks', '#e86c2f'),
    '.sldasm': ('ensamblaje',  'solidworks', '#f0a500'),
    '.slddrw': ('plano',       'solidworks', '#3498db'),
    '.prt':    ('pieza',       'solidworks', '#e86c2f'),
    '.asm':    ('ensamblaje',  'solidworks', '#f0a500'),
    '.drw':    ('plano',       'solidworks', '#3498db'),
    '.dwg':    ('plano',       'autocad',    '#3498db'),
    '.dxf':    ('plano',       'autocad',    '#3498db'),
    '.ipt':    ('pieza',       'inventor',   '#e86c2f'),
    '.iam':    ('ensamblaje',  'inventor',   '#f0a500'),
    '.idw':    ('plano',       'inventor',   '#3498db'),
    '.step':   ('pieza',       'neutro',     '#2ecc71'),
    '.stp':    ('pieza',       'neutro',     '#2ecc71'),
    '.iges':   ('pieza',       'neutro',     '#2ecc71'),
    '.igs':    ('pieza',       'neutro',     '#2ecc71'),
    '.stl':    ('pieza',       'neutro',     '#9b59b6'),
    '.obj':    ('pieza',       'neutro',     '#9b59b6'),
    '.pdf':    ('plano',       'documento',  '#e74c3c'),
    '.xlsx':   ('bom',         'documento',  '#2ecc71'),
    '.xls':    ('bom',         'documento',  '#2ecc71'),
}

EXT_ICONS = {
    '.sldprt': '⬡', '.sldasm': '⬢', '.slddrw': '▦',
    '.prt': '⬡', '.asm': '⬢', '.drw': '▦',
    '.dwg': '▦', '.dxf': '▦',
    '.ipt': '⬡', '.iam': '⬢', '.idw': '▦',
    '.step': '◈', '.stp': '◈', '.iges': '◈', '.igs': '◈',
    '.stl': '◉', '.obj': '◉',
    '.pdf': '▤', '.xlsx': '▦', '.xls': '▦',
    'folder': '▸', 'folder_open': '▾',
}


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def calc_hash(filepath):
    try:
        h = hashlib.md5()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def get_doc_info(filepath):
    """Busca si el archivo ya está registrado en PLM."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM plm_documentos WHERE ruta_origen=?", (filepath,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def format_size(size):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


@plm_explorer.route('/plm/explorer')
def plm_explorer_view():
    """Vista principal del explorador PDM."""
    home = os.path.expanduser('~')

    # Calcular rutas reales de accesos rápidos según SO
    if sys.platform == 'win32':
        import string
        drives = [f"{d}:\\" for d in string.ascii_uppercase
                  if os.path.exists(f"{d}:\\")]
        roots = drives
        # Intentar rutas típicas de Windows en español e inglés
        docs_candidates  = ['Documentos', 'Documents', 'Mis documentos']
        desk_candidates  = ['Escritorio', 'Desktop']
    else:
        roots = [home, '/']
        docs_candidates  = ['Documents', 'Documentos']
        desk_candidates  = ['Desktop', 'Escritorio']

    def first_existing(base, candidates):
        for c in candidates:
            p = os.path.join(base, c)
            if os.path.exists(p):
                return p
        return base  # fallback al home

    path_home    = home
    path_docs    = first_existing(home, docs_candidates)
    path_desktop = first_existing(home, desk_candidates)

    # Watchfolders configuradas
    conn = get_db()
    watchfolders = conn.execute("SELECT * FROM plm_watchfolders ORDER BY id").fetchall()
    favoritos = [dict(wf) for wf in watchfolders]

    # Stats PLM
    stats = {
        'total': conn.execute("SELECT COUNT(*) FROM plm_documentos").fetchone()[0],
        'en_diseno': conn.execute("SELECT COUNT(*) FROM plm_documentos WHERE estado='en_diseno'").fetchone()[0],
        'liberados': conn.execute("SELECT COUNT(*) FROM plm_documentos WHERE estado='liberado'").fetchone()[0],
    }
    conn.close()

    return render_template('plm_explorer.html',
                           roots=roots, favoritos=favoritos, stats=stats,
                           path_home=path_home,
                           path_docs=path_docs,
                           path_desktop=path_desktop)


@plm_explorer.route('/plm/explorer/browse')
def plm_browse():
    """API: lista contenido de una carpeta."""
    path = request.args.get('path', os.path.expanduser('~'))

    # Seguridad básica: normalizar ruta
    path = os.path.normpath(path)

    if not os.path.exists(path):
        return jsonify({'error': 'Ruta no existe', 'path': path, 'items': []})

    items = []

    try:
        entries = list(os.scandir(path))
    except PermissionError:
        return jsonify({'error': 'Sin permiso', 'path': path, 'items': []})

    # Carpetas primero, luego archivos
    entries.sort(key=lambda e: (not e.is_dir(), e.name.lower()))

    for entry in entries:
        if entry.name.startswith('.'):
            continue  # Ocultar archivos ocultos

        try:
            stat = entry.stat()
        except Exception:
            continue

        ext = os.path.splitext(entry.name)[1].lower()

        if entry.is_dir():
            # Contar archivos CAD dentro (nivel superficial)
            try:
                cad_count = sum(
                    1 for f in os.scandir(entry.path)
                    if os.path.splitext(f.name)[1].lower() in EXT_CAD
                )
            except Exception:
                cad_count = 0

            items.append({
                'type': 'folder',
                'name': entry.name,
                'path': entry.path,
                'icon': EXT_ICONS['folder'],
                'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%d/%m/%Y %H:%M'),
                'cad_count': cad_count,
                'is_cad': cad_count > 0,
            })
        else:
            is_cad = ext in EXT_CAD
            cad_info = EXT_CAD.get(ext, None)
            doc_plm = get_doc_info(entry.path) if is_cad else None

            items.append({
                'type': 'file',
                'name': entry.name,
                'path': entry.path,
                'ext': ext,
                'icon': EXT_ICONS.get(ext, '▪'),
                'size': format_size(stat.st_size),
                'size_bytes': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%d/%m/%Y %H:%M'),
                'is_cad': is_cad,
                'tipo': cad_info[0] if cad_info else None,
                'software': cad_info[1] if cad_info else None,
                'color': cad_info[2] if cad_info else '#555',
                'plm_registrado': doc_plm is not None,
                'plm_codigo': doc_plm['codigo'] if doc_plm else None,
                'plm_estado': doc_plm['estado'] if doc_plm else None,
                'plm_id': doc_plm['id'] if doc_plm else None,
            })

    # Breadcrumb
    parts = []
    current = path
    while True:
        parent = os.path.dirname(current)
        if parent == current:
            parts.insert(0, {'name': current, 'path': current})
            break
        parts.insert(0, {'name': os.path.basename(current), 'path': current})
        current = parent

    return jsonify({
        'path': path,
        'parent': os.path.dirname(path) if os.path.dirname(path) != path else None,
        'breadcrumb': parts,
        'items': items,
        'total': len(items),
        'cad_total': sum(1 for i in items if i.get('is_cad')),
    })


@plm_explorer.route('/plm/explorer/open', methods=['POST'])
def plm_open_file():
    """Abre un archivo con su programa predeterminado."""
    data = request.get_json()
    filepath = data.get('path', '')

    if not os.path.isfile(filepath):
        return jsonify({'ok': False, 'error': 'Archivo no encontrado'})

    try:
        if sys.platform == 'win32':
            os.startfile(filepath)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', filepath])
        else:
            subprocess.Popen(['xdg-open', filepath])
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@plm_explorer.route('/plm/explorer/register', methods=['POST'])
def plm_register_file():
    """Registra un archivo CAD en el PLM."""
    data = request.get_json()
    filepath = data.get('path', '')
    proyecto_id = data.get('proyecto_id')

    if not os.path.isfile(filepath):
        return jsonify({'ok': False, 'error': 'Archivo no encontrado'})

    ext = os.path.splitext(filepath)[1].lower()
    if ext not in EXT_CAD:
        return jsonify({'ok': False, 'error': 'Extensión no soportada'})

    tipo, software, _ = EXT_CAD[ext]
    nombre = os.path.splitext(os.path.basename(filepath))[0]
    nuevo_hash = calc_hash(filepath)

    conn = get_db()

    # Comprobar si ya existe
    existing = conn.execute(
        "SELECT id, codigo FROM plm_documentos WHERE ruta_origen=?", (filepath,)
    ).fetchone()

    if existing:
        conn.close()
        return jsonify({'ok': False, 'error': f'Ya registrado como {existing["codigo"]}',
                        'plm_id': existing['id'], 'codigo': existing['codigo']})

    # Generar código
    prefijos = {'pieza': 'PZA', 'ensamblaje': 'ENS', 'plano': 'PLN', 'otro': 'DOC', 'bom': 'BOM'}
    pref = prefijos.get(tipo, 'DOC')
    row = conn.execute(
        "SELECT codigo FROM plm_documentos WHERE tipo=? ORDER BY id DESC LIMIT 1", (tipo,)
    ).fetchone()
    num = int(row['codigo'].split('-')[-1]) + 1 if row else 1
    codigo = f"{pref}-{datetime.now().year}-{num:04d}"

    # Copiar al vault
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    vault_name = f"{codigo}_{ts}{ext}"
    shutil.copy2(filepath, os.path.join(VAULT_DIR, vault_name))

    conn.execute('''INSERT INTO plm_documentos
        (codigo, nombre, tipo, software, ruta_origen, archivo_vault, hash_md5, estado, proyecto_id)
        VALUES (?,?,?,?,?,?,?,?,?)''',
        (codigo, nombre, tipo, software, filepath, vault_name, nuevo_hash, 'en_diseno',
         proyecto_id or None))
    doc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute('''INSERT INTO plm_revisiones (documento_id, revision, descripcion_cambio)
        VALUES (?,?,?)''', (doc_id, 'A', 'Registrado desde explorador PLM'))
    conn.execute('INSERT INTO plm_log (documento_id, accion, detalle) VALUES (?,?,?)',
                 (doc_id, 'REGISTRADO', f"Desde explorador: {filepath}"))
    conn.commit()
    conn.close()

    return jsonify({'ok': True, 'codigo': codigo, 'plm_id': doc_id, 'tipo': tipo, 'software': software})


@plm_explorer.route('/plm/explorer/add_watchfolder', methods=['POST'])
def plm_add_watchfolder_explorer():
    """Añade una carpeta a watch folders desde el explorador."""
    data = request.get_json()
    ruta = data.get('path', '')
    software = data.get('software', '')

    if not os.path.isdir(ruta):
        return jsonify({'ok': False, 'error': 'No es una carpeta válida'})

    conn = get_db()
    try:
        conn.execute("INSERT INTO plm_watchfolders (ruta, software) VALUES (?,?)",
                     (ruta, software))
        conn.commit()
        result = {'ok': True}
    except Exception:
        result = {'ok': False, 'error': 'Ya está en watch folders'}
    conn.close()
    return jsonify(result)


@plm_explorer.route('/plm/explorer/proyectos')
def plm_get_proyectos():
    conn = get_db()
    proyectos = conn.execute(
        "SELECT id, nombre FROM proyectos WHERE estado NOT IN ('entregado','cancelado') ORDER BY nombre"
    ).fetchall()
    conn.close()
    return jsonify([dict(p) for p in proyectos])