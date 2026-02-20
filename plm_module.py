"""
PLM Module — JA · ERP
Gestión de: Documentos CAD, BOM, Revisiones/Estados
"""

import sqlite3, os, json, hashlib, shutil
from datetime import datetime, date
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, send_file

plm = Blueprint('plm', __name__)

DB = os.path.join(os.path.dirname(__file__), 'crm.db')
VAULT_DIR = os.path.join(os.path.dirname(__file__), 'plm_vault')  # Donde se guardan copias

os.makedirs(VAULT_DIR, exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

# ── INIT TABLES ───────────────────────────────────────────────────────────────
def init_plm_db():
    conn = get_db()
    c = conn.cursor()

    # Documentos CAD (piezas, ensamblajes, planos)
    c.execute('''CREATE TABLE IF NOT EXISTS plm_documentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proyecto_id INTEGER,
        codigo TEXT UNIQUE NOT NULL,
        nombre TEXT NOT NULL,
        tipo TEXT NOT NULL,          -- pieza | ensamblaje | plano | otro
        software TEXT,               -- solidworks | autocad | otro
        descripcion TEXT,
        estado TEXT DEFAULT 'en_diseno',  -- en_diseno | revision | aprobado | liberado | obsoleto
        ruta_origen TEXT,            -- ruta original en el PC del usuario
        archivo_vault TEXT,          -- nombre del archivo en plm_vault
        hash_md5 TEXT,               -- para detectar cambios
        creado TEXT DEFAULT CURRENT_TIMESTAMP,
        modificado TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (proyecto_id) REFERENCES proyectos(id))''')

    # Revisiones de cada documento
    c.execute('''CREATE TABLE IF NOT EXISTS plm_revisiones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        documento_id INTEGER NOT NULL,
        revision TEXT NOT NULL,      -- A, B, C... o 01, 02...
        descripcion_cambio TEXT,
        estado TEXT DEFAULT 'en_diseno',
        archivo_vault TEXT,
        hash_md5 TEXT,
        creado_por TEXT DEFAULT 'JA',
        fecha TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (documento_id) REFERENCES plm_documentos(id))''')

    # BOM — Bill of Materials
    c.execute('''CREATE TABLE IF NOT EXISTS plm_bom (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proyecto_id INTEGER,
        nombre TEXT NOT NULL,
        descripcion TEXT,
        estado TEXT DEFAULT 'borrador',  -- borrador | revision | aprobado | liberado
        creado TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (proyecto_id) REFERENCES proyectos(id))''')

    # Líneas de BOM
    c.execute('''CREATE TABLE IF NOT EXISTS plm_bom_lineas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bom_id INTEGER NOT NULL,
        documento_id INTEGER,        -- referencia a pieza/ensamblaje (opcional)
        pos INTEGER,                 -- posición en BOM
        codigo TEXT,
        descripcion TEXT NOT NULL,
        cantidad REAL DEFAULT 1,
        unidad TEXT DEFAULT 'ud',
        material TEXT,
        proveedor TEXT,
        notas TEXT,
        FOREIGN KEY (bom_id) REFERENCES plm_bom(id),
        FOREIGN KEY (documento_id) REFERENCES plm_documentos(id))''')

    # Log de cambios (audit trail)
    c.execute('''CREATE TABLE IF NOT EXISTS plm_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        documento_id INTEGER,
        accion TEXT,
        detalle TEXT,
        fecha TEXT DEFAULT CURRENT_TIMESTAMP)''')

    # Watch folder config
    c.execute('''CREATE TABLE IF NOT EXISTS plm_watchfolders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ruta TEXT UNIQUE NOT NULL,
        software TEXT,
        activa INTEGER DEFAULT 1,
        ultima_sync TEXT)''')

    conn.commit()
    conn.close()


def log_accion(documento_id, accion, detalle=''):
    conn = get_db()
    conn.execute('INSERT INTO plm_log (documento_id, accion, detalle) VALUES (?,?,?)',
                 (documento_id, accion, detalle))
    conn.commit()
    conn.close()


def calc_hash(filepath):
    try:
        h = hashlib.md5()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()
    except:
        return None


def next_codigo(tipo):
    prefijos = {'pieza': 'PZA', 'ensamblaje': 'ENS', 'plano': 'PLN', 'otro': 'DOC'}
    pref = prefijos.get(tipo, 'DOC')
    conn = get_db()
    row = conn.execute(
        "SELECT codigo FROM plm_documentos WHERE tipo=? ORDER BY id DESC LIMIT 1", (tipo,)
    ).fetchone()
    conn.close()
    if row:
        try:
            num = int(row['codigo'].split('-')[-1]) + 1
        except:
            num = 1
    else:
        num = 1
    return f"{pref}-{date.today().year}-{num:04d}"


# ── RUTAS PLM ─────────────────────────────────────────────────────────────────

@plm.route('/plm')
def plm_index():
    conn = get_db()
    docs = conn.execute('''
        SELECT d.*, p.nombre as proyecto_nombre
        FROM plm_documentos d
        LEFT JOIN proyectos p ON d.proyecto_id = p.id
        ORDER BY d.modificado DESC
    ''').fetchall()
    boms = conn.execute('''
        SELECT b.*, p.nombre as proyecto_nombre,
               (SELECT COUNT(*) FROM plm_bom_lineas WHERE bom_id=b.id) as num_lineas
        FROM plm_bom b
        LEFT JOIN proyectos p ON b.proyecto_id = p.id
        ORDER BY b.creado DESC
    ''').fetchall()
    proyectos = conn.execute("SELECT id, nombre FROM proyectos WHERE estado NOT IN ('entregado','cancelado') ORDER BY nombre").fetchall()
    watchfolders = conn.execute("SELECT * FROM plm_watchfolders ORDER BY id").fetchall()
    stats = {
        'total_docs': conn.execute("SELECT COUNT(*) FROM plm_documentos").fetchone()[0],
        'en_diseno': conn.execute("SELECT COUNT(*) FROM plm_documentos WHERE estado='en_diseno'").fetchone()[0],
        'revision': conn.execute("SELECT COUNT(*) FROM plm_documentos WHERE estado='revision'").fetchone()[0],
        'aprobados': conn.execute("SELECT COUNT(*) FROM plm_documentos WHERE estado='aprobado'").fetchone()[0],
        'liberados': conn.execute("SELECT COUNT(*) FROM plm_documentos WHERE estado='liberado'").fetchone()[0],
        'total_boms': conn.execute("SELECT COUNT(*) FROM plm_bom").fetchone()[0],
    }
    conn.close()
    return render_template('plm.html', docs=docs, boms=boms, proyectos=proyectos,
                           watchfolders=watchfolders, stats=stats)


@plm.route('/plm/documento/nuevo', methods=['POST'])
def plm_nuevo_documento():
    data = request.form
    conn = get_db()
    codigo = next_codigo(data.get('tipo', 'pieza'))
    conn.execute('''INSERT INTO plm_documentos
        (proyecto_id, codigo, nombre, tipo, software, descripcion, estado, ruta_origen)
        VALUES (?,?,?,?,?,?,?,?)''', (
        data.get('proyecto_id') or None,
        codigo,
        data['nombre'],
        data.get('tipo', 'pieza'),
        data.get('software', ''),
        data.get('descripcion', ''),
        data.get('estado', 'en_diseno'),
        data.get('ruta_origen', '')
    ))
    doc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    # Crear revisión inicial A
    conn.execute('''INSERT INTO plm_revisiones (documento_id, revision, descripcion_cambio, estado)
        VALUES (?,?,?,?)''', (doc_id, 'A', 'Revisión inicial', data.get('estado', 'en_diseno')))
    conn.commit()
    log_accion(doc_id, 'CREADO', f"Código: {codigo}")
    conn.close()
    return redirect(url_for('plm.plm_index'))


@plm.route('/plm/documento/<int:doc_id>')
def plm_documento_detalle(doc_id):
    conn = get_db()
    doc = conn.execute('''
        SELECT d.*, p.nombre as proyecto_nombre
        FROM plm_documentos d
        LEFT JOIN proyectos p ON d.proyecto_id = p.id
        WHERE d.id=?''', (doc_id,)).fetchone()
    revisiones = conn.execute(
        "SELECT * FROM plm_revisiones WHERE documento_id=? ORDER BY id DESC", (doc_id,)
    ).fetchall()
    log = conn.execute(
        "SELECT * FROM plm_log WHERE documento_id=? ORDER BY id DESC LIMIT 20", (doc_id,)
    ).fetchall()
    proyectos = conn.execute("SELECT id, nombre FROM proyectos ORDER BY nombre").fetchall()
    conn.close()
    return render_template('plm_detalle.html', doc=doc, revisiones=revisiones,
                           log=log, proyectos=proyectos)


@plm.route('/plm/documento/<int:doc_id>/estado', methods=['POST'])
def plm_cambiar_estado(doc_id):
    nuevo_estado = request.form['estado']
    conn = get_db()
    old = conn.execute("SELECT estado FROM plm_documentos WHERE id=?", (doc_id,)).fetchone()
    conn.execute("UPDATE plm_documentos SET estado=?, modificado=? WHERE id=?",
                 (nuevo_estado, datetime.now().isoformat(), doc_id))
    conn.commit()
    log_accion(doc_id, 'ESTADO', f"{old['estado']} → {nuevo_estado}")
    conn.close()
    return redirect(url_for('plm.plm_documento_detalle', doc_id=doc_id))


@plm.route('/plm/documento/<int:doc_id>/revision', methods=['POST'])
def plm_nueva_revision(doc_id):
    conn = get_db()
    last = conn.execute(
        "SELECT revision FROM plm_revisiones WHERE documento_id=? ORDER BY id DESC LIMIT 1",
        (doc_id,)
    ).fetchone()
    # Siguiente letra de revisión
    letras = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    if last and last['revision'] in letras:
        idx = letras.index(last['revision'])
        nueva_rev = letras[idx + 1] if idx + 1 < len(letras) else 'A1'
    else:
        nueva_rev = 'A'
    conn.execute('''INSERT INTO plm_revisiones (documento_id, revision, descripcion_cambio, estado)
        VALUES (?,?,?,?)''', (doc_id, nueva_rev, request.form.get('descripcion', ''),
                               request.form.get('estado', 'en_diseno')))
    conn.execute("UPDATE plm_documentos SET modificado=? WHERE id=?",
                 (datetime.now().isoformat(), doc_id))
    conn.commit()
    log_accion(doc_id, 'REVISION', f"Nueva revisión {nueva_rev}")
    conn.close()
    return redirect(url_for('plm.plm_documento_detalle', doc_id=doc_id))


# ── BOM ───────────────────────────────────────────────────────────────────────

@plm.route('/plm/bom/nuevo', methods=['POST'])
def plm_nueva_bom():
    data = request.form
    conn = get_db()
    conn.execute("INSERT INTO plm_bom (proyecto_id, nombre, descripcion) VALUES (?,?,?)",
                 (data.get('proyecto_id') or None, data['nombre'], data.get('descripcion', '')))
    conn.commit()
    conn.close()
    return redirect(url_for('plm.plm_index'))


@plm.route('/plm/bom/<int:bom_id>')
def plm_bom_detalle(bom_id):
    conn = get_db()
    bom = conn.execute('''
        SELECT b.*, p.nombre as proyecto_nombre
        FROM plm_bom b LEFT JOIN proyectos p ON b.proyecto_id=p.id
        WHERE b.id=?''', (bom_id,)).fetchone()
    lineas = conn.execute('''
        SELECT l.*, d.codigo as doc_codigo
        FROM plm_bom_lineas l
        LEFT JOIN plm_documentos d ON l.documento_id=d.id
        WHERE l.bom_id=? ORDER BY l.pos''', (bom_id,)).fetchall()
    docs = conn.execute("SELECT id, codigo, nombre, tipo FROM plm_documentos ORDER BY codigo").fetchall()
    proyectos = conn.execute("SELECT id, nombre FROM proyectos ORDER BY nombre").fetchall()
    conn.close()
    return render_template('plm_bom.html', bom=bom, lineas=lineas, docs=docs, proyectos=proyectos)


@plm.route('/plm/bom/<int:bom_id>/linea', methods=['POST'])
def plm_add_linea_bom(bom_id):
    data = request.form
    conn = get_db()
    max_pos = conn.execute("SELECT MAX(pos) FROM plm_bom_lineas WHERE bom_id=?", (bom_id,)).fetchone()[0] or 0
    conn.execute('''INSERT INTO plm_bom_lineas
        (bom_id, documento_id, pos, codigo, descripcion, cantidad, unidad, material, proveedor, notas)
        VALUES (?,?,?,?,?,?,?,?,?,?)''', (
        bom_id,
        data.get('documento_id') or None,
        max_pos + 10,
        data.get('codigo', ''),
        data['descripcion'],
        float(data.get('cantidad', 1)),
        data.get('unidad', 'ud'),
        data.get('material', ''),
        data.get('proveedor', ''),
        data.get('notas', '')
    ))
    conn.commit()
    conn.close()
    return redirect(url_for('plm.plm_bom_detalle', bom_id=bom_id))


@plm.route('/plm/bom/<int:bom_id>/linea/<int:linea_id>/delete', methods=['POST'])
def plm_delete_linea_bom(bom_id, linea_id):
    conn = get_db()
    conn.execute("DELETE FROM plm_bom_lineas WHERE id=?", (linea_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('plm.plm_bom_detalle', bom_id=bom_id))


@plm.route('/plm/bom/<int:bom_id>/estado', methods=['POST'])
def plm_bom_estado(bom_id):
    conn = get_db()
    conn.execute("UPDATE plm_bom SET estado=? WHERE id=?",
                 (request.form['estado'], bom_id))
    conn.commit()
    conn.close()
    return redirect(url_for('plm.plm_bom_detalle', bom_id=bom_id))


# ── WATCH FOLDER ──────────────────────────────────────────────────────────────

@plm.route('/plm/watchfolder/add', methods=['POST'])
def plm_add_watchfolder():
    conn = get_db()
    try:
        conn.execute("INSERT INTO plm_watchfolders (ruta, software) VALUES (?,?)",
                     (request.form['ruta'], request.form.get('software', '')))
        conn.commit()
    except:
        pass
    conn.close()
    return redirect(url_for('plm.plm_index'))


@plm.route('/plm/watchfolder/<int:wf_id>/toggle', methods=['POST'])
def plm_toggle_watchfolder(wf_id):
    conn = get_db()
    wf = conn.execute("SELECT activa FROM plm_watchfolders WHERE id=?", (wf_id,)).fetchone()
    conn.execute("UPDATE plm_watchfolders SET activa=? WHERE id=?",
                 (0 if wf['activa'] else 1, wf_id))
    conn.commit()
    conn.close()
    return redirect(url_for('plm.plm_index'))


@plm.route('/plm/watchfolder/<int:wf_id>/delete', methods=['POST'])
def plm_delete_watchfolder(wf_id):
    conn = get_db()
    conn.execute("DELETE FROM plm_watchfolders WHERE id=?", (wf_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('plm.plm_index'))


@plm.route('/plm/sync', methods=['POST'])
def plm_sync_manual():
    """Sincronización manual de watch folders"""
    conn = get_db()
    wfs = conn.execute("SELECT * FROM plm_watchfolders WHERE activa=1").fetchall()
    nuevos = 0
    actualizados = 0

    EXT_MAP = {
        '.sldprt': ('pieza', 'solidworks'),
        '.sldasm': ('ensamblaje', 'solidworks'),
        '.slddrw': ('plano', 'solidworks'),
        '.prt':    ('pieza', 'solidworks'),
        '.asm':    ('ensamblaje', 'solidworks'),
        '.drw':    ('plano', 'solidworks'),
        '.dwg':    ('plano', 'autocad'),
        '.dxf':    ('plano', 'autocad'),
        '.ipt':    ('pieza', 'autocad'),
        '.iam':    ('ensamblaje', 'autocad'),
        '.idw':    ('plano', 'autocad'),
        '.step':   ('pieza', 'otro'),
        '.stp':    ('pieza', 'otro'),
        '.iges':   ('pieza', 'otro'),
        '.stl':    ('pieza', 'otro'),
    }

    for wf in wfs:
        ruta = wf['ruta']
        if not os.path.exists(ruta):
            continue
        for fname in os.listdir(ruta):
            fpath = os.path.join(ruta, fname)
            if not os.path.isfile(fpath):
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext not in EXT_MAP:
                continue

            tipo, software = EXT_MAP[ext]
            nuevo_hash = calc_hash(fpath)
            nombre_sin_ext = os.path.splitext(fname)[0]

            # ¿Existe ya este documento por ruta origen?
            existing = conn.execute(
                "SELECT * FROM plm_documentos WHERE ruta_origen=?", (fpath,)
            ).fetchone()

            if existing:
                # Comprobar si cambió
                if existing['hash_md5'] != nuevo_hash:
                    # Copiar al vault como nueva versión
                    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                    vault_name = f"{existing['codigo']}_rev_{ts}{ext}"
                    shutil.copy2(fpath, os.path.join(VAULT_DIR, vault_name))
                    conn.execute('''UPDATE plm_documentos
                        SET hash_md5=?, archivo_vault=?, modificado=?, estado='en_diseno'
                        WHERE id=?''',
                        (nuevo_hash, vault_name, datetime.now().isoformat(), existing['id']))
                    log_accion(existing['id'], 'SYNC_CAMBIO', f"Hash actualizado: {vault_name}")
                    actualizados += 1
            else:
                # Nuevo documento
                codigo = next_codigo(tipo)
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                vault_name = f"{codigo}_{ts}{ext}"
                shutil.copy2(fpath, os.path.join(VAULT_DIR, vault_name))
                conn.execute('''INSERT INTO plm_documentos
                    (codigo, nombre, tipo, software, ruta_origen, archivo_vault, hash_md5, estado)
                    VALUES (?,?,?,?,?,?,?,?)''',
                    (codigo, nombre_sin_ext, tipo, software, fpath, vault_name, nuevo_hash, 'en_diseno'))
                doc_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
                conn.execute('''INSERT INTO plm_revisiones (documento_id, revision, descripcion_cambio)
                    VALUES (?,?,?)''', (doc_id, 'A', 'Importado automáticamente'))
                log_accion(doc_id, 'SYNC_NUEVO', f"Detectado: {fpath}")
                nuevos += 1

        conn.execute("UPDATE plm_watchfolders SET ultima_sync=? WHERE id=?",
                     (datetime.now().isoformat(), wf['id']))

    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'nuevos': nuevos, 'actualizados': actualizados})


@plm.route('/plm/api/stats')
def plm_api_stats():
    conn = get_db()
    stats = {
        'total': conn.execute("SELECT COUNT(*) FROM plm_documentos").fetchone()[0],
        'en_diseno': conn.execute("SELECT COUNT(*) FROM plm_documentos WHERE estado='en_diseno'").fetchone()[0],
        'revision': conn.execute("SELECT COUNT(*) FROM plm_documentos WHERE estado='revision'").fetchone()[0],
        'aprobado': conn.execute("SELECT COUNT(*) FROM plm_documentos WHERE estado='aprobado'").fetchone()[0],
        'liberado': conn.execute("SELECT COUNT(*) FROM plm_documentos WHERE estado='liberado'").fetchone()[0],
    }
    conn.close()
    return jsonify(stats)
# ── RECENT ────────────────────────────────────────────────────────────────────
@plm.route('/plm/api/recent')
def plm_api_recent():
    conn = get_db()
    docs = conn.execute(
        "SELECT id, codigo, nombre, tipo, estado, ruta_origen FROM plm_documentos ORDER BY modificado DESC LIMIT 10"
    ).fetchall()
    conn.close()
    return jsonify([dict(d) for d in docs])