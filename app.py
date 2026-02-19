"""
JA · ERP - Sistema de Gestión Completo
Módulos: CRM, Proyectos, Facturación, Proveedores
Ejecutar: python app.py  →  http://localhost:5000
"""

from flask import Flask, render_template, request, jsonify, redirect, url_for, make_response
import sqlite3, os, json
from datetime import datetime, date
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.colors import HexColor
import io

app = Flask(__name__)
DB = os.path.join(os.path.dirname(__file__), 'crm.db')

# ── DB ────────────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS clientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL, empresa TEXT, email TEXT, telefono TEXT,
        sector TEXT, estado TEXT DEFAULT 'lead', notas TEXT,
        fecha_alta TEXT DEFAULT CURRENT_DATE)''')

    c.execute('''CREATE TABLE IF NOT EXISTS presupuestos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER, numero TEXT UNIQUE, descripcion TEXT,
        servicio TEXT, importe REAL, estado TEXT DEFAULT 'borrador',
        fecha_emision TEXT, fecha_validez TEXT, notas TEXT,
        FOREIGN KEY (cliente_id) REFERENCES clientes(id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS comunicaciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER, tipo TEXT, asunto TEXT, contenido TEXT,
        fecha TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (cliente_id) REFERENCES clientes(id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS proyectos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER, presupuesto_id INTEGER,
        referencia TEXT UNIQUE, nombre TEXT NOT NULL,
        servicio TEXT, estado TEXT DEFAULT 'en_diseno',
        progreso INTEGER DEFAULT 0,
        fecha_inicio TEXT, fecha_entrega TEXT,
        importe REAL DEFAULT 0,
        horas_estimadas REAL DEFAULT 0,
        notas TEXT,
        fecha_creacion TEXT DEFAULT CURRENT_DATE,
        FOREIGN KEY (cliente_id) REFERENCES clientes(id),
        FOREIGN KEY (presupuesto_id) REFERENCES presupuestos(id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS horas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proyecto_id INTEGER NOT NULL,
        fecha TEXT DEFAULT CURRENT_DATE,
        horas REAL NOT NULL,
        descripcion TEXT,
        FOREIGN KEY (proyecto_id) REFERENCES proyectos(id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS proyecto_proveedores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proyecto_id INTEGER, proveedor_id INTEGER,
        concepto TEXT, importe REAL DEFAULT 0, estado TEXT DEFAULT 'pendiente',
        FOREIGN KEY (proyecto_id) REFERENCES proyectos(id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS facturas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER, proyecto_id INTEGER, albaran_id INTEGER,
        numero TEXT UNIQUE, concepto TEXT,
        base REAL, iva REAL DEFAULT 21, irpf REAL DEFAULT 15,
        estado TEXT DEFAULT 'pendiente',
        fecha_emision TEXT, fecha_vencimiento TEXT, fecha_cobro TEXT,
        notas TEXT,
        FOREIGN KEY (cliente_id) REFERENCES clientes(id),
        FOREIGN KEY (proyecto_id) REFERENCES proyectos(id),
        FOREIGN KEY (albaran_id) REFERENCES albaranes(id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS proveedores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL, empresa TEXT, email TEXT, telefono TEXT,
        especialidad TEXT, valoracion REAL DEFAULT 5.0,
        estado TEXT DEFAULT 'activo', notas TEXT,
        fecha_alta TEXT DEFAULT CURRENT_DATE)''')

    c.execute('''CREATE TABLE IF NOT EXISTS pedidos_proveedor (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proveedor_id INTEGER, proyecto_id INTEGER,
        numero TEXT UNIQUE, concepto TEXT,
        importe REAL DEFAULT 0, estado TEXT DEFAULT 'pendiente',
        fecha_pedido TEXT DEFAULT CURRENT_DATE, fecha_entrega_esperada TEXT,
        notas TEXT,
        FOREIGN KEY (proveedor_id) REFERENCES proveedores(id),
        FOREIGN KEY (proyecto_id) REFERENCES proyectos(id))''')

    c.execute('''CREATE TABLE IF NOT EXISTS albaranes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pedido_id INTEGER NOT NULL,
        proyecto_id INTEGER NOT NULL,
        numero TEXT UNIQUE,
        fecha_recepcion TEXT DEFAULT CURRENT_DATE,
        estado TEXT DEFAULT 'no_facturado',
        conformidad TEXT,
        notas TEXT,
        FOREIGN KEY (pedido_id) REFERENCES pedidos_proveedor(id),
        FOREIGN KEY (proyecto_id) REFERENCES proyectos(id))''')

    # Demo data
    c.execute("SELECT COUNT(*) FROM clientes")
    if c.fetchone()[0] == 0:
        clientes = [
            ('Carlos Martínez','Mecánica del Norte S.L.','carlos@mecanica-norte.es','612 345 678','Maquinaria','activo','Cliente recurrente'),
            ('Ana Gómez','Grúas y Elevación S.A.','ana@gruas-elevacion.es','698 765 432','Elevación','activo','Interesada en apoyo técnico mensual'),
            ('Pedro Ruiz','Taller Metálico Ruiz','pedro@tallerruiz.es','655 111 222','Carpintería metálica','lead','Presupuesto enviado'),
            ('María Ferrón','Industrias Ferrón','maria@ferron.es','677 888 999','Metalurgia','activo',''),
            ('Javier García','Automatismos García','javier@automatismos.es','600 333 444','Maquinaria','lead',''),
        ]
        c.executemany('INSERT INTO clientes (nombre,empresa,email,telefono,sector,estado,notas) VALUES (?,?,?,?,?,?,?)', clientes)

        proveedores = [
            ('Roberto Sanz','TallerCNC S.L.','rsanz@tallercnc.es','611 222 333','Mecanizado CNC',4.9,'activo','Entrega puntual, calidad excelente'),
            ('Laura Prieto','Protolab 3D','info@protolab.es','622 333 444','Impresión 3D',4.7,'activo','FDM y SLA, buenos precios'),
            ('Fernando Vega','MetalSheet Ibérica','fvega@metalsheet.es','633 444 555','Corte láser y chapa',4.5,'activo',''),
            ('Studio Render','Render Studio','hola@renderstudio.es','644 555 666','Visualización 3D',4.8,'activo','Fotorrealismo de calidad'),
        ]
        c.executemany('INSERT INTO proveedores (nombre,empresa,email,telefono,especialidad,valoracion,estado,notas) VALUES (?,?,?,?,?,?,?,?)', proveedores)

        presupuestos = [
            (1,'PRE-2025-003','Diseño soporte CNC con planos ISO','Diseño mecánico',850.0,'aceptado','2025-01-20','2025-02-20',''),
            (2,'PRE-2025-002','Conjunto elevador — modelado 3D','Diseño mecánico',1200.0,'aceptado','2025-01-10','2025-02-10',''),
            (4,'PRE-2025-001','Renderizado catálogo piezas','Renderizado 3D',480.0,'enviado','2025-02-01','2025-03-01',''),
        ]
        c.executemany('INSERT INTO presupuestos (cliente_id,numero,descripcion,servicio,importe,estado,fecha_emision,fecha_validez,notas) VALUES (?,?,?,?,?,?,?,?,?)', presupuestos)

        proyectos = [
            (1,1,'PRY-2025-005','Soporte CNC — Mecánica del Norte','Diseño mecánico','en_diseno',35,'2025-02-10','2025-02-28',650,8,''),
            (2,2,'PRY-2025-004','Conjunto elevador — Grúas S.A.','Diseño mecánico','en_fabricacion',70,'2025-01-28','2025-03-10',1200,20,'Proveedor CNC asignado'),
            (3,None,'PRY-2025-003','Planos ISO — Taller Ruiz','Planos técnicos','revision_cliente',90,'2025-02-01','2025-02-20',320,6,''),
            (4,None,'PRY-2025-002','Renderizado 3D — Ferrón','Renderizado 3D','en_diseno',55,'2025-02-05','2025-02-25',480,12,''),
            (2,None,'PRY-2025-001','Apoyo técnico feb — Grúas','Apoyo técnico','activo',20,'2025-02-01','2025-02-28',800,40,''),
        ]
        c.executemany('INSERT INTO proyectos (cliente_id,presupuesto_id,referencia,nombre,servicio,estado,progreso,fecha_inicio,fecha_entrega,importe,horas_estimadas,notas) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', proyectos)

        horas_demo = [
            (1,'2025-02-10',2.5,'Reunión briefing y análisis de requisitos'),
            (1,'2025-02-12',3.0,'Modelado 3D pieza principal'),
            (2,'2025-02-01',4.0,'Inicio diseño conjunto'),
            (2,'2025-02-05',6.0,'Modelado y ensamblaje'),
            (2,'2025-02-10',5.0,'Planos técnicos y BOM'),
            (3,'2025-02-01',2.0,'Revisión planos existentes'),
            (3,'2025-02-03',4.0,'Redibujado ISO/DIN'),
        ]
        c.executemany('INSERT INTO horas (proyecto_id,fecha,horas,descripcion) VALUES (?,?,?,?)', horas_demo)

        facturas = [
            (2,2,'FAC-2025-004','Conjunto elevador PRY-2025-004 — 70% avance',840,21,15,'pendiente','2025-02-10','2025-03-10',None,''),
            (1,1,'FAC-2025-003','Diseño soporte CNC PRY-2025-005 — anticipo 50%',325,21,15,'cobrada','2025-02-01','2025-03-01','2025-02-08',''),
            (3,3,'FAC-2025-002','Planos técnicos PRY-2025-003',320,21,15,'pendiente','2025-02-15','2025-03-15',None,''),
            (1,None,'FAC-2025-001','Consultoría materiales enero',180,21,15,'cobrada','2025-01-20','2025-02-20','2025-01-28',''),
        ]
        c.executemany('INSERT INTO facturas (cliente_id,proyecto_id,numero,concepto,base,iva,irpf,estado,fecha_emision,fecha_vencimiento,fecha_cobro,notas) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', facturas)

        pedidos = [
            (1,2,'PED-2025-003','Mecanizado CNC pieza soporte PRY-004',680,'en_produccion','2025-02-05','2025-03-05',''),
            (2,1,'PED-2025-002','Prototipo FDM PRY-005',95,'pendiente','2025-02-12','2025-02-22',''),
            (3,3,'PED-2025-001','Corte láser chapa PRY-003',210,'entregado','2025-02-01','2025-02-18','Entregado en plazo'),
        ]
        c.executemany('INSERT INTO pedidos_proveedor (proveedor_id,proyecto_id,numero,concepto,importe,estado,fecha_pedido,fecha_entrega_esperada,notas) VALUES (?,?,?,?,?,?,?,?,?)', pedidos)

    conn.commit()
    conn.close()

# ── HELPERS ───────────────────────────────────────────────────────────────────
def next_num(tabla, campo, prefijo):
    conn = get_db()
    row = conn.execute(f"SELECT {campo} FROM {tabla} ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    num = int(row[0].split('-')[-1]) + 1 if row else 1
    return f"{prefijo}-{date.today().year}-{num:03d}"

# ── INDEX ─────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    conn = get_db()
    stats = {
        'clientes_activos': conn.execute("SELECT COUNT(*) FROM clientes WHERE estado='activo'").fetchone()[0],
        'proyectos_activos': conn.execute("SELECT COUNT(*) FROM proyectos WHERE estado NOT IN ('entregado','cancelado')").fetchone()[0],
        'albaranes_pendientes': conn.execute("SELECT COUNT(*) FROM albaranes WHERE estado='no_facturado'").fetchone()[0],
        'facturas_pendientes': conn.execute("SELECT COUNT(*) FROM facturas WHERE estado='pendiente'").fetchone()[0],
        'facturado_mes': conn.execute("SELECT COALESCE(SUM(base),0) FROM facturas WHERE strftime('%Y-%m',fecha_emision)=strftime('%Y-%m','now')").fetchone()[0],
    }
    proyectos = conn.execute('''SELECT p.*, c.nombre as cliente_nombre, c.empresa as cliente_empresa
        FROM proyectos p JOIN clientes c ON c.id=p.cliente_id
        WHERE p.estado NOT IN ('entregado','cancelado') ORDER BY p.fecha_entrega LIMIT 5''').fetchall()
    actividad = conn.execute('''
        SELECT 'factura' as tipo, numero as ref, fecha_emision as fecha, concepto as texto FROM facturas
        UNION ALL
        SELECT 'proyecto', referencia, fecha_creacion, nombre FROM proyectos
        UNION ALL
        SELECT 'albaran', numero, fecha_recepcion, 'Albarán recibido' FROM albaranes
        ORDER BY fecha DESC LIMIT 6''').fetchall()
    conn.close()
    return render_template('dashboard.html', stats=stats, proyectos=proyectos, actividad=actividad)

# ── CRM ───────────────────────────────────────────────────────────────────────
@app.route('/clientes')
def clientes():
    conn = get_db()
    clientes = conn.execute('''SELECT c.*,
        COUNT(DISTINCT p.id) as num_presupuestos,
        COALESCE(SUM(CASE WHEN p.estado='aceptado' THEN p.importe ELSE 0 END),0) as volumen
        FROM clientes c LEFT JOIN presupuestos p ON p.cliente_id=c.id
        GROUP BY c.id ORDER BY c.fecha_alta DESC''').fetchall()
    stats = {
        'total': conn.execute("SELECT COUNT(*) FROM clientes").fetchone()[0],
        'activos': conn.execute("SELECT COUNT(*) FROM clientes WHERE estado='activo'").fetchone()[0],
        'leads': conn.execute("SELECT COUNT(*) FROM clientes WHERE estado='lead'").fetchone()[0],
        'presupuestos_pendientes': conn.execute("SELECT COUNT(*) FROM presupuestos WHERE estado='enviado'").fetchone()[0],
    }
    conn.close()
    return render_template('clientes.html', clientes=clientes, stats=stats)

@app.route('/cliente/<int:id>')
def cliente_detalle(id):
    conn = get_db()
    cliente = conn.execute('SELECT * FROM clientes WHERE id=?',(id,)).fetchone()
    presupuestos = conn.execute('SELECT * FROM presupuestos WHERE cliente_id=? ORDER BY fecha_emision DESC',(id,)).fetchall()
    comunicaciones = conn.execute('SELECT * FROM comunicaciones WHERE cliente_id=? ORDER BY fecha DESC',(id,)).fetchall()
    proyectos = conn.execute('SELECT * FROM proyectos WHERE cliente_id=? ORDER BY fecha_creacion DESC',(id,)).fetchall()
    conn.close()
    return render_template('cliente_detalle.html', cliente=cliente, presupuestos=presupuestos, comunicaciones=comunicaciones, proyectos=proyectos)

@app.route('/cliente/nuevo', methods=['GET','POST'])
def cliente_nuevo():
    if request.method == 'POST':
        conn = get_db()
        conn.execute('INSERT INTO clientes (nombre,empresa,email,telefono,sector,estado,notas) VALUES (?,?,?,?,?,?,?)',
            (request.form['nombre'],request.form['empresa'],request.form['email'],
             request.form['telefono'],request.form['sector'],request.form['estado'],request.form['notas']))
        conn.commit()
        id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return redirect(url_for('cliente_detalle', id=id))
    return render_template('cliente_form.html', cliente=None)

@app.route('/cliente/<int:id>/editar', methods=['GET','POST'])
def cliente_editar(id):
    conn = get_db()
    if request.method == 'POST':
        conn.execute('UPDATE clientes SET nombre=?,empresa=?,email=?,telefono=?,sector=?,estado=?,notas=? WHERE id=?',
            (request.form['nombre'],request.form['empresa'],request.form['email'],
             request.form['telefono'],request.form['sector'],request.form['estado'],request.form['notas'],id))
        conn.commit(); conn.close()
        return redirect(url_for('cliente_detalle', id=id))
    cliente = conn.execute('SELECT * FROM clientes WHERE id=?',(id,)).fetchone()
    conn.close()
    return render_template('cliente_form.html', cliente=cliente)

@app.route('/cliente/<int:id>/eliminar', methods=['POST'])
def cliente_eliminar(id):
    conn = get_db()
    for t in ['comunicaciones','presupuestos','proyectos']:
        conn.execute(f'DELETE FROM {t} WHERE cliente_id=?',(id,))
    conn.execute('DELETE FROM clientes WHERE id=?',(id,))
    conn.commit(); conn.close()
    return redirect(url_for('clientes'))

@app.route('/presupuesto/nuevo/<int:cliente_id>', methods=['GET','POST'])
def presupuesto_nuevo(cliente_id):
    conn = get_db()
    if request.method == 'POST':
        num = next_num('presupuestos','numero','PRE')
        conn.execute('INSERT INTO presupuestos (cliente_id,numero,descripcion,servicio,importe,estado,fecha_emision,fecha_validez,notas) VALUES (?,?,?,?,?,?,?,?,?)',
            (cliente_id,num,request.form['descripcion'],request.form['servicio'],
             float(request.form['importe']),request.form['estado'],
             request.form['fecha_emision'],request.form['fecha_validez'],request.form['notas']))
        conn.commit(); conn.close()
        return redirect(url_for('cliente_detalle', id=cliente_id))
    cliente = conn.execute('SELECT * FROM clientes WHERE id=?',(cliente_id,)).fetchone()
    conn.close()
    return render_template('presupuesto_form.html', cliente=cliente,
        num=next_num('presupuestos','numero','PRE'),
        today=date.today().isoformat(), validez=date.today().isoformat())

@app.route('/presupuesto/<int:id>/estado', methods=['POST'])
def presupuesto_estado(id):
    data = request.get_json()
    conn = get_db()
    
    # Update presupuesto state
    conn.execute('UPDATE presupuestos SET estado=? WHERE id=?',(data['estado'],id))
    
    # If accepted → auto-create project
    if data['estado'] == 'aceptado':
        pres = conn.execute('SELECT * FROM presupuestos WHERE id=?',(id,)).fetchone()
        # Check if project already exists
        existing = conn.execute('SELECT id FROM proyectos WHERE presupuesto_id=?',(id,)).fetchone()
        if not existing:
            ref = next_num('proyectos','referencia','PRY')
            conn.execute('''INSERT INTO proyectos 
                (cliente_id, presupuesto_id, referencia, nombre, servicio, estado, importe, fecha_inicio)
                VALUES (?,?,?,?,?,?,?,date('now'))''',
                (pres['cliente_id'], id, ref, pres['descripcion'], pres['servicio'], 
                 'en_diseno', pres['importe']))
    
    conn.commit()
    conn.close()
    return jsonify({'ok':True})

@app.route('/comunicacion/nueva/<int:cliente_id>', methods=['POST'])
def comunicacion_nueva(cliente_id):
    conn = get_db()
    conn.execute('INSERT INTO comunicaciones (cliente_id,tipo,asunto,contenido) VALUES (?,?,?,?)',
        (cliente_id,request.form['tipo'],request.form['asunto'],request.form['contenido']))
    conn.commit(); conn.close()
    return redirect(url_for('cliente_detalle', id=cliente_id))

# ── PRESUPUESTOS ──────────────────────────────────────────────────────────────
@app.route('/presupuestos')
def presupuestos_listado():
    conn = get_db()
    presupuestos = conn.execute('''SELECT p.*, 
        c.nombre as cliente_nombre, c.empresa as cliente_empresa,
        pry.id as proyecto_id, pry.referencia as proyecto_ref
        FROM presupuestos p 
        JOIN clientes c ON c.id = p.cliente_id
        LEFT JOIN proyectos pry ON pry.presupuesto_id = p.id
        ORDER BY p.fecha_emision DESC''').fetchall()
    stats = {
        'total': conn.execute("SELECT COUNT(*) FROM presupuestos").fetchone()[0],
        'borradores': conn.execute("SELECT COUNT(*) FROM presupuestos WHERE estado='borrador'").fetchone()[0],
        'enviados': conn.execute("SELECT COUNT(*) FROM presupuestos WHERE estado='enviado'").fetchone()[0],
        'aceptados': conn.execute("SELECT COUNT(*) FROM presupuestos WHERE estado='aceptado'").fetchone()[0],
        'rechazados': conn.execute("SELECT COUNT(*) FROM presupuestos WHERE estado='rechazado'").fetchone()[0],
        'importe_enviados': conn.execute("SELECT COALESCE(SUM(importe),0) FROM presupuestos WHERE estado='enviado'").fetchone()[0],
    }
    clientes = conn.execute("SELECT id,nombre,empresa FROM clientes ORDER BY nombre").fetchall()
    conn.close()
    return render_template('presupuestos.html', presupuestos=presupuestos, stats=stats, clientes=clientes)

@app.route('/presupuesto/<int:id>')
def presupuesto_detalle(id):
    conn = get_db()
    presupuesto = conn.execute('''SELECT p.*, 
        c.nombre as cliente_nombre, c.empresa as cliente_empresa, c.email as cliente_email
        FROM presupuestos p JOIN clientes c ON c.id = p.cliente_id
        WHERE p.id=?''',(id,)).fetchone()
    proyecto = conn.execute('SELECT * FROM proyectos WHERE presupuesto_id=?',(id,)).fetchone()
    conn.close()
    return render_template('presupuesto_detalle.html', presupuesto=presupuesto, proyecto=proyecto)

@app.route('/presupuesto/<int:id>/editar', methods=['POST'])
def presupuesto_editar(id):
    conn = get_db()
    conn.execute('''UPDATE presupuestos SET descripcion=?, servicio=?, importe=?, 
        fecha_emision=?, fecha_validez=?, notas=? WHERE id=?''',
        (request.form['descripcion'], request.form['servicio'], float(request.form['importe']),
         request.form['fecha_emision'], request.form['fecha_validez'], request.form.get('notas',''), id))
    conn.commit()
    conn.close()
    return redirect(url_for('presupuesto_detalle', id=id))

@app.route('/presupuesto/<int:id>/eliminar', methods=['POST'])
def presupuesto_eliminar(id):
    conn = get_db()
    # Check if has proyecto linked
    proyecto = conn.execute('SELECT id FROM proyectos WHERE presupuesto_id=?',(id,)).fetchone()
    if proyecto:
        conn.close()
        return jsonify({'error': 'No se puede eliminar: tiene un proyecto asociado'}), 400
    conn.execute('DELETE FROM presupuestos WHERE id=?',(id,))
    conn.commit()
    conn.close()
    return redirect(url_for('presupuestos_listado'))

# ── PROYECTOS ─────────────────────────────────────────────────────────────────
@app.route('/proyectos')
def proyectos():
    conn = get_db()
    proyectos = conn.execute('''SELECT p.*, c.nombre as cliente_nombre, c.empresa as cliente_empresa,
        COALESCE((SELECT SUM(h.horas) FROM horas h WHERE h.proyecto_id=p.id),0) as horas_reales
        FROM proyectos p JOIN clientes c ON c.id=p.cliente_id ORDER BY p.fecha_entrega''').fetchall()
    stats = {
        'activos': conn.execute("SELECT COUNT(*) FROM proyectos WHERE estado NOT IN ('entregado','cancelado')").fetchone()[0],
        'en_diseno': conn.execute("SELECT COUNT(*) FROM proyectos WHERE estado='en_diseno'").fetchone()[0],
        'en_fabricacion': conn.execute("SELECT COUNT(*) FROM proyectos WHERE estado='en_fabricacion'").fetchone()[0],
        'entregados_mes': conn.execute("SELECT COUNT(*) FROM proyectos WHERE estado='entregado' AND strftime('%Y-%m',fecha_entrega)=strftime('%Y-%m','now')").fetchone()[0],
    }
    clientes = conn.execute("SELECT id,nombre,empresa FROM clientes ORDER BY nombre").fetchall()
    proveedores = conn.execute("SELECT id,nombre,empresa FROM proveedores WHERE estado='activo' ORDER BY nombre").fetchall()
    conn.close()
    return render_template('proyectos.html', proyectos=proyectos, stats=stats, clientes=clientes, proveedores=proveedores)

@app.route('/proyecto/nuevo', methods=['POST'])
def proyecto_nuevo():
    conn = get_db()
    ref = next_num('proyectos','referencia','PRY')
    conn.execute('''INSERT INTO proyectos (cliente_id,referencia,nombre,servicio,estado,progreso,
        fecha_inicio,fecha_entrega,importe,horas_estimadas,notas)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
        (request.form['cliente_id'], ref, request.form['nombre'], request.form['servicio'],
         request.form['estado'], int(request.form.get('progreso',0)),
         request.form['fecha_inicio'], request.form['fecha_entrega'],
         float(request.form.get('importe',0)), float(request.form.get('horas_estimadas',0)),
         request.form.get('notas','')))
    conn.commit()
    id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return redirect(url_for('proyecto_detalle', id=id))

@app.route('/proyecto/<int:id>')
def proyecto_detalle(id):
    conn = get_db()
    proyecto = conn.execute('''SELECT p.*, c.nombre as cliente_nombre, c.empresa as cliente_empresa
        FROM proyectos p JOIN clientes c ON c.id=p.cliente_id WHERE p.id=?''',(id,)).fetchone()
    horas = conn.execute('SELECT * FROM horas WHERE proyecto_id=? ORDER BY fecha DESC',(id,)).fetchall()
    horas_total = conn.execute('SELECT COALESCE(SUM(horas),0) FROM horas WHERE proyecto_id=?',(id,)).fetchone()[0]
    pedidos = conn.execute('''SELECT pp.*, pv.nombre as proveedor_nombre, pv.empresa as proveedor_empresa
        FROM pedidos_proveedor pp JOIN proveedores pv ON pv.id=pp.proveedor_id
        WHERE pp.proyecto_id=? ORDER BY pp.fecha_pedido DESC''',(id,)).fetchall()
    proveedores = conn.execute("SELECT id,nombre,empresa,especialidad FROM proveedores WHERE estado='activo'").fetchall()
    conn.close()
    return render_template('proyecto_detalle.html', proyecto=proyecto, horas=horas,
        horas_total=horas_total, pedidos=pedidos, proveedores=proveedores)

@app.route('/proyecto/<int:id>/editar', methods=['POST'])
def proyecto_editar(id):
    conn = get_db()
    conn.execute('''UPDATE proyectos SET nombre=?,servicio=?,estado=?,progreso=?,
        fecha_inicio=?,fecha_entrega=?,importe=?,horas_estimadas=?,notas=? WHERE id=?''',
        (request.form['nombre'],request.form['servicio'],request.form['estado'],
         int(request.form.get('progreso',0)),request.form['fecha_inicio'],
         request.form['fecha_entrega'],float(request.form.get('importe',0)),
         float(request.form.get('horas_estimadas',0)),request.form.get('notas',''),id))
    conn.commit(); conn.close()
    return redirect(url_for('proyecto_detalle', id=id))

@app.route('/proyecto/<int:id>/progreso', methods=['POST'])
def proyecto_progreso(id):
    data = request.get_json()
    conn = get_db()
    conn.execute('UPDATE proyectos SET progreso=?,estado=? WHERE id=?',(data['progreso'],data['estado'],id))
    conn.commit(); conn.close()
    return jsonify({'ok':True})

@app.route('/horas/nueva/<int:proyecto_id>', methods=['POST'])
def horas_nueva(proyecto_id):
    conn = get_db()
    conn.execute('INSERT INTO horas (proyecto_id,fecha,horas,descripcion) VALUES (?,?,?,?)',
        (proyecto_id,request.form['fecha'],float(request.form['horas']),request.form['descripcion']))
    conn.commit(); conn.close()
    return redirect(url_for('proyecto_detalle', id=proyecto_id))

@app.route('/horas/<int:id>/eliminar', methods=['POST'])
def horas_eliminar(id):
    conn = get_db()
    proy_id = conn.execute('SELECT proyecto_id FROM horas WHERE id=?',(id,)).fetchone()[0]
    conn.execute('DELETE FROM horas WHERE id=?',(id,))
    conn.commit(); conn.close()
    return redirect(url_for('proyecto_detalle', id=proy_id))

@app.route('/api/gantt')
def api_gantt():
    conn = get_db()
    proyectos = conn.execute('''SELECT p.id, p.referencia, p.nombre, p.fecha_inicio, p.fecha_entrega,
        p.estado, p.progreso, c.empresa as cliente
        FROM proyectos p JOIN clientes c ON c.id=p.cliente_id
        WHERE p.fecha_inicio IS NOT NULL AND p.fecha_entrega IS NOT NULL
        ORDER BY p.fecha_inicio''').fetchall()
    conn.close()
    return jsonify([dict(p) for p in proyectos])

# ── FACTURACIÓN ───────────────────────────────────────────────────────────────
@app.route('/facturacion')
def facturacion():
    conn = get_db()
    facturas = conn.execute('''SELECT f.*, c.nombre as cliente_nombre, c.empresa as cliente_empresa,
        p.referencia as proyecto_ref
        FROM facturas f JOIN clientes c ON c.id=f.cliente_id
        LEFT JOIN proyectos p ON p.id=f.proyecto_id
        ORDER BY f.fecha_emision DESC''').fetchall()
    stats = {
        'cobrado_mes': conn.execute("SELECT COALESCE(SUM(base),0) FROM facturas WHERE estado='cobrada' AND strftime('%Y-%m',fecha_emision)=strftime('%Y-%m','now')").fetchone()[0],
        'pendiente': conn.execute("SELECT COALESCE(SUM(base),0) FROM facturas WHERE estado='pendiente'").fetchone()[0],
        'vencidas': conn.execute("SELECT COUNT(*) FROM facturas WHERE estado='pendiente' AND fecha_vencimiento < date('now')").fetchone()[0],
        'base_trimestre': conn.execute("SELECT COALESCE(SUM(base),0) FROM facturas WHERE strftime('%Y-%m',fecha_emision)>=strftime('%Y-%m',date('now','-3 months'))").fetchone()[0],
    }
    clientes = conn.execute("SELECT id,nombre,empresa FROM clientes ORDER BY nombre").fetchall()
    proyectos = conn.execute("SELECT id,referencia,nombre FROM proyectos ORDER BY referencia DESC").fetchall()
    conn.close()
    return render_template('facturacion.html', facturas=facturas, stats=stats, clientes=clientes, proyectos=proyectos)

@app.route('/factura/nueva', methods=['POST'])
def factura_nueva():
    conn = get_db()
    num = next_num('facturas','numero','FAC')
    conn.execute('''INSERT INTO facturas (cliente_id,proyecto_id,numero,concepto,base,iva,irpf,
        estado,fecha_emision,fecha_vencimiento,notas) VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
        (request.form['cliente_id'],
         request.form['proyecto_id'] if request.form['proyecto_id'] else None,
         num, request.form['concepto'], float(request.form['base']),
         float(request.form.get('iva',21)), float(request.form.get('irpf',15)),
         request.form['estado'], request.form['fecha_emision'],
         request.form['fecha_vencimiento'], request.form.get('notas','')))
    conn.commit(); conn.close()
    return redirect(url_for('facturacion'))

@app.route('/factura/<int:id>/cobrar', methods=['POST'])
def factura_cobrar(id):
    conn = get_db()
    conn.execute("UPDATE facturas SET estado='cobrada', fecha_cobro=date('now') WHERE id=?", (id,))
    conn.commit(); conn.close()
    return jsonify({'ok':True})

@app.route('/factura/<int:id>/eliminar', methods=['POST'])
def factura_eliminar(id):
    conn = get_db()
    conn.execute('DELETE FROM facturas WHERE id=?',(id,))
    conn.commit(); conn.close()
    return redirect(url_for('facturacion'))

@app.route('/factura/<int:id>/pdf')
def factura_pdf(id):
    conn = get_db()
    f = conn.execute('''SELECT f.*, c.nombre as cliente_nombre, c.empresa as cliente_empresa,
        c.email as cliente_email, p.referencia as proyecto_ref
        FROM facturas f JOIN clientes c ON c.id=f.cliente_id
        LEFT JOIN proyectos p ON p.id=f.proyecto_id WHERE f.id=?''',(id,)).fetchone()
    conn.close()

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    MARGIN = 18*mm
    ORANGE = HexColor('#e86c2f'); DARK = HexColor('#1a1a1a'); WHITE = HexColor('#ffffff')
    CREAM = HexColor('#f0ece6'); MUTED = HexColor('#888888'); TEXT = HexColor('#333333')
    BGLIGHT = HexColor('#fafaf8'); BORDER = HexColor('#e0ddd8'); AMBER = HexColor('#f0a500')

    c.setFillColor(BGLIGHT); c.rect(0,0,W,H,fill=1,stroke=0)
    # Header
    c.setFillColor(DARK); c.rect(0,H-50*mm,W,50*mm,fill=1,stroke=0)
    c.setFillColor(ORANGE); c.rect(0,H-50*mm,W*0.6,3,fill=1,stroke=0)
    c.setFillColor(AMBER); c.rect(W*0.6,H-50*mm,W*0.4,3,fill=1,stroke=0)
    # grid
    c.setStrokeColor(ORANGE); c.setStrokeAlpha(0.05); c.setLineWidth(0.3)
    for x in range(0,int(W),30):
        c.line(x,H-50*mm,x,H)
    for y in range(int(H-50*mm),int(H),30):
        c.line(0,y,W,y)
    c.setStrokeAlpha(1)
    c.setFillColor(WHITE); c.setFont("Helvetica-Bold",22)
    c.drawString(MARGIN,H-22*mm,"JUAN ANTONIO")
    c.setFillColor(ORANGE); c.setFont("Helvetica",7)
    c.drawString(MARGIN,H-29*mm,"DISEÑO MECÁNICO INDUSTRIAL")
    c.setFillColor(HexColor('#2a2a2a')); c.setFont("Helvetica-Bold",28)
    c.drawRightString(W-MARGIN,H-22*mm,"FACTURA")
    c.setFillColor(MUTED); c.setFont("Helvetica",7)
    c.drawRightString(W-MARGIN,H-30*mm,f"Nº {f['numero']}")
    # Meta
    y = H-60*mm
    def meta(lbl,val,x,y):
        c.setFillColor(MUTED); c.setFont("Helvetica",6); c.drawString(x,y,lbl.upper())
        c.setStrokeColor(ORANGE); c.setLineWidth(0.5); c.line(x,y-1.5*mm,x+40*mm,y-1.5*mm)
        c.setFillColor(TEXT); c.setFont("Helvetica",8.5)
        for i,l in enumerate(val):
            c.drawString(x,y-5*mm-i*4.5*mm,l)
    meta("Emisor",["Juan Antonio","Ingeniero de Diseño Industrial","juanantonio@diseñomecanico.es"],MARGIN,y)
    meta("Fecha de factura",[f['fecha_emision'] or ''],W/2+10*mm,y)
    meta("Cliente",[f['cliente_nombre'],f['cliente_empresa'] or '',f['cliente_email'] or ''],MARGIN,y-28*mm)
    meta("Vencimiento",[f['fecha_vencimiento'] or ''],W/2+10*mm,y-28*mm)
    # Table
    ty = y-56*mm
    c.setStrokeColor(BORDER); c.setLineWidth(0.5); c.line(MARGIN,ty,W-MARGIN,ty)
    th = ty-8*mm
    c.setFillColor(DARK); c.rect(MARGIN,th-2*mm,W-2*MARGIN,8*mm,fill=1,stroke=0)
    c.setFillColor(WHITE); c.setFont("Helvetica",6.5)
    c.drawString(MARGIN+2*mm,th+1*mm,"CONCEPTO")
    c.drawRightString(W-MARGIN-2*mm,th+1*mm,"IMPORTE")
    row_y = th-5*mm
    c.setFillColor(HexColor('#f5f3f0')); c.rect(MARGIN,row_y-6*mm,W-2*MARGIN,8*mm,fill=1,stroke=0)
    c.setFillColor(TEXT); c.setFont("Helvetica",8.5)
    c.drawString(MARGIN+2*mm,row_y-2.5*mm,f['concepto'] or '')
    if f['proyecto_ref']:
        c.setFont("Helvetica",7); c.setFillColor(MUTED)
        c.drawString(MARGIN+2*mm,row_y-6.5*mm,f"Proyecto: {f['proyecto_ref']}")
    c.setFont("Helvetica",8.5); c.setFillColor(TEXT)
    c.drawRightString(W-MARGIN-2*mm,row_y-2.5*mm,f"{f['base']:.2f} €")
    # Totals
    tots_y = row_y-18*mm
    base = f['base']; iva_a = base*f['iva']/100; irpf_a = base*f['irpf']/100; total = base+iva_a-irpf_a
    tx = W-MARGIN-80*mm
    def tot_row(lbl,val,y,final=False):
        if final:
            c.setFillColor(ORANGE); c.rect(tx-3*mm,y-2*mm,80*mm,7*mm,fill=1,stroke=0)
            c.setFillColor(WHITE); c.setFont("Helvetica-Bold",9)
        else:
            c.setStrokeColor(BORDER); c.setLineWidth(0.3); c.line(tx,y-2*mm,tx+76*mm,y-2*mm)
            c.setFillColor(MUTED); c.setFont("Helvetica",8)
        c.drawString(tx,y+1.5*mm,lbl); c.drawRightString(tx+76*mm,y+1.5*mm,val)
        return y-7*mm
    tots_y = tot_row("Base imponible",f"{base:.2f} €",tots_y)
    tots_y = tot_row(f"IVA ({f['iva']:.0f}%)",f"+{iva_a:.2f} €",tots_y)
    tots_y = tot_row(f"IRPF ({f['irpf']:.0f}%)",f"-{irpf_a:.2f} €",tots_y)
    tot_row("TOTAL A PAGAR",f"{total:.2f} €",tots_y,final=True)
    # Footer
    c.setFillColor(CREAM); c.rect(0,0,W,12*mm,fill=1,stroke=0)
    c.setStrokeColor(BORDER); c.setLineWidth(0.5); c.line(0,12*mm,W,12*mm)
    c.setFillColor(MUTED); c.setFont("Helvetica",6.5)
    c.drawString(MARGIN,4.5*mm,"juanantonio@diseñomecanico.es  ·  juanantonio-mecanico.es")
    c.setFillColor(ORANGE); c.drawRightString(W-MARGIN,4.5*mm,"DISEÑO · FABRICACIÓN · ENTREGA")
    c.save()
    buf.seek(0)
    response = make_response(buf.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename={f["numero"]}.pdf'
    return response

# ── PROVEEDORES ───────────────────────────────────────────────────────────────
@app.route('/proveedores')
def proveedores():
    conn = get_db()
    proveedores = conn.execute('''SELECT pv.*,
        COUNT(DISTINCT pp.id) as num_pedidos,
        COALESCE(SUM(pp.importe),0) as gasto_total
        FROM proveedores pv LEFT JOIN pedidos_proveedor pp ON pp.proveedor_id=pv.id
        GROUP BY pv.id ORDER BY pv.nombre''').fetchall()
    stats = {
        'total': conn.execute("SELECT COUNT(*) FROM proveedores").fetchone()[0],
        'activos': conn.execute("SELECT COUNT(*) FROM proveedores WHERE estado='activo'").fetchone()[0],
        'pedidos_activos': conn.execute("SELECT COUNT(*) FROM pedidos_proveedor WHERE estado NOT IN ('entregado','cancelado')").fetchone()[0],
        'gasto_mes': conn.execute("SELECT COALESCE(SUM(importe),0) FROM pedidos_proveedor WHERE strftime('%Y-%m',fecha_pedido)=strftime('%Y-%m','now')").fetchone()[0],
    }
    proyectos = conn.execute("SELECT id,referencia,nombre FROM proyectos ORDER BY referencia DESC").fetchall()
    conn.close()
    return render_template('proveedores.html', proveedores=proveedores, stats=stats, proyectos=proyectos)

@app.route('/proveedor/nuevo', methods=['POST'])
def proveedor_nuevo():
    conn = get_db()
    conn.execute('INSERT INTO proveedores (nombre,empresa,email,telefono,especialidad,valoracion,estado,notas) VALUES (?,?,?,?,?,?,?,?)',
        (request.form['nombre'],request.form['empresa'],request.form['email'],
         request.form['telefono'],request.form['especialidad'],
         float(request.form.get('valoracion',5)),request.form['estado'],request.form.get('notas','')))
    conn.commit()
    id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return redirect(url_for('proveedor_detalle', id=id))

@app.route('/proveedor/<int:id>')
def proveedor_detalle(id):
    conn = get_db()
    proveedor = conn.execute('SELECT * FROM proveedores WHERE id=?',(id,)).fetchone()
    pedidos = conn.execute('''SELECT pp.*, p.nombre as proyecto_nombre, p.referencia as proyecto_ref
        FROM pedidos_proveedor pp LEFT JOIN proyectos p ON p.id=pp.proyecto_id
        WHERE pp.proveedor_id=? ORDER BY pp.fecha_pedido DESC''',(id,)).fetchall()
    gasto_total = conn.execute('SELECT COALESCE(SUM(importe),0) FROM pedidos_proveedor WHERE proveedor_id=?',(id,)).fetchone()[0]
    proyectos = conn.execute("SELECT id,referencia,nombre FROM proyectos ORDER BY referencia DESC").fetchall()
    conn.close()
    return render_template('proveedor_detalle.html', proveedor=proveedor, pedidos=pedidos,
        gasto_total=gasto_total, proyectos=proyectos)

@app.route('/proveedor/<int:id>/editar', methods=['POST'])
def proveedor_editar(id):
    conn = get_db()
    conn.execute('UPDATE proveedores SET nombre=?,empresa=?,email=?,telefono=?,especialidad=?,valoracion=?,estado=?,notas=? WHERE id=?',
        (request.form['nombre'],request.form['empresa'],request.form['email'],
         request.form['telefono'],request.form['especialidad'],
         float(request.form.get('valoracion',5)),request.form['estado'],
         request.form.get('notas',''),id))
    conn.commit(); conn.close()
    return redirect(url_for('proveedor_detalle', id=id))

@app.route('/pedido/nuevo/<int:proveedor_id>', methods=['POST'])
def pedido_nuevo(proveedor_id):
    conn = get_db()
    num = next_num('pedidos_proveedor','numero','PED')
    conn.execute('''INSERT INTO pedidos_proveedor (proveedor_id,proyecto_id,numero,concepto,importe,
        estado,fecha_pedido,fecha_entrega_esperada,notas) VALUES (?,?,?,?,?,?,?,?,?)''',
        (proveedor_id,
         request.form['proyecto_id'] if request.form.get('proyecto_id') else None,
         num,request.form['concepto'],float(request.form.get('importe',0)),
         request.form['estado'],request.form['fecha_pedido'],
         request.form['fecha_entrega_esperada'],request.form.get('notas','')))
    conn.commit(); conn.close()
    return redirect(url_for('proveedor_detalle', id=proveedor_id))

@app.route('/pedido/<int:id>/estado', methods=['POST'])
def pedido_estado(id):
    data = request.get_json()
    conn = get_db()
    
    pedido = conn.execute('SELECT * FROM pedidos_proveedor WHERE id=?',(id,)).fetchone()
    conn.execute('UPDATE pedidos_proveedor SET estado=? WHERE id=?',(data['estado'],id))
    
    # If recibido → auto-create albaran
    if data['estado'] == 'recibido':
        # Check if albaran already exists
        existing = conn.execute('SELECT id FROM albaranes WHERE pedido_id=?',(id,)).fetchone()
        if not existing:
            num = next_num('albaranes','numero','ALB')
            conn.execute('''INSERT INTO albaranes 
                (pedido_id, proyecto_id, numero, fecha_recepcion, estado, conformidad)
                VALUES (?,?,?,date('now'),'no_facturado','Conforme')''',
                (id, pedido['proyecto_id'], num))
    
    conn.commit()
    conn.close()
    return jsonify({'ok':True})

# ── PEDIDOS A PROVEEDORES ─────────────────────────────────────────────────────
@app.route('/pedidos')
def pedidos_listado():
    conn = get_db()
    pedidos = conn.execute('''SELECT pp.*, 
        pv.nombre as proveedor_nombre, pv.empresa as proveedor_empresa,
        p.referencia as proyecto_ref, p.nombre as proyecto_nombre,
        c.nombre as cliente_nombre, c.empresa as cliente_empresa,
        a.id as albaran_id, a.numero as albaran_numero
        FROM pedidos_proveedor pp
        JOIN proveedores pv ON pv.id = pp.proveedor_id
        LEFT JOIN proyectos p ON p.id = pp.proyecto_id
        LEFT JOIN clientes c ON c.id = p.cliente_id
        LEFT JOIN albaranes a ON a.pedido_id = pp.id
        ORDER BY pp.fecha_pedido DESC''').fetchall()
    stats = {
        'total': conn.execute("SELECT COUNT(*) FROM pedidos_proveedor").fetchone()[0],
        'pendientes': conn.execute("SELECT COUNT(*) FROM pedidos_proveedor WHERE estado='pendiente'").fetchone()[0],
        'en_produccion': conn.execute("SELECT COUNT(*) FROM pedidos_proveedor WHERE estado='en_produccion'").fetchone()[0],
        'en_transito': conn.execute("SELECT COUNT(*) FROM pedidos_proveedor WHERE estado='en_transito'").fetchone()[0],
        'recibidos': conn.execute("SELECT COUNT(*) FROM pedidos_proveedor WHERE estado='recibido'").fetchone()[0],
        'importe_pendiente': conn.execute("SELECT COALESCE(SUM(importe),0) FROM pedidos_proveedor WHERE estado NOT IN ('recibido','cancelado')").fetchone()[0],
    }
    proveedores = conn.execute("SELECT DISTINCT nombre FROM proveedores ORDER BY nombre").fetchall()
    clientes = conn.execute("SELECT DISTINCT nombre FROM clientes ORDER BY nombre").fetchall()
    proyectos = conn.execute("SELECT DISTINCT referencia FROM proyectos ORDER BY referencia DESC").fetchall()
    conn.close()
    return render_template('pedidos.html', pedidos=pedidos, stats=stats, 
                         proveedores=proveedores, clientes=clientes, proyectos=proyectos)

@app.route('/pedido/<int:id>/detalle')
def pedido_detalle_view(id):
    conn = get_db()
    pedido = conn.execute('''SELECT pp.*,
        pv.nombre as proveedor_nombre, pv.empresa as proveedor_empresa, 
        pv.email as proveedor_email, pv.telefono as proveedor_telefono,
        p.referencia as proyecto_ref, p.nombre as proyecto_nombre, p.cliente_id,
        c.nombre as cliente_nombre, c.empresa as cliente_empresa,
        a.id as albaran_id, a.numero as albaran_numero, a.fecha_recepcion as albaran_fecha
        FROM pedidos_proveedor pp
        JOIN proveedores pv ON pv.id = pp.proveedor_id
        LEFT JOIN proyectos p ON p.id = pp.proyecto_id
        LEFT JOIN clientes c ON c.id = p.cliente_id
        LEFT JOIN albaranes a ON a.pedido_id = pp.id
        WHERE pp.id=?''',(id,)).fetchone()
    conn.close()
    return render_template('pedido_detalle.html', pedido=pedido)

# ── ALBARANES ─────────────────────────────────────────────────────────────────
@app.route('/albaranes')
def albaranes():
    conn = get_db()
    albaranes = conn.execute('''SELECT a.*, 
        p.referencia as proyecto_ref, p.nombre as proyecto_nombre,
        c.nombre as cliente_nombre,
        ped.numero as pedido_numero, ped.concepto as pedido_concepto,
        prov.nombre as proveedor_nombre
        FROM albaranes a
        JOIN proyectos p ON p.id = a.proyecto_id
        JOIN clientes c ON c.id = p.cliente_id
        JOIN pedidos_proveedor ped ON ped.id = a.pedido_id
        JOIN proveedores prov ON prov.id = ped.proveedor_id
        ORDER BY a.fecha_recepcion DESC''').fetchall()
    stats = {
        'total': conn.execute("SELECT COUNT(*) FROM albaranes").fetchone()[0],
        'no_facturados': conn.execute("SELECT COUNT(*) FROM albaranes WHERE estado='no_facturado'").fetchone()[0],
        'facturados': conn.execute("SELECT COUNT(*) FROM albaranes WHERE estado='facturado'").fetchone()[0],
    }
    conn.close()
    return render_template('albaranes.html', albaranes=albaranes, stats=stats)

@app.route('/albaran/<int:id>')
def albaran_detalle(id):
    conn = get_db()
    albaran = conn.execute('''SELECT a.*,
        p.referencia as proyecto_ref, p.nombre as proyecto_nombre, p.cliente_id, p.importe as proyecto_importe,
        c.nombre as cliente_nombre, c.empresa as cliente_empresa,
        ped.numero as pedido_numero, ped.concepto as pedido_concepto, ped.importe as pedido_importe,
        prov.nombre as proveedor_nombre, prov.empresa as proveedor_empresa
        FROM albaranes a
        JOIN proyectos p ON p.id = a.proyecto_id
        JOIN clientes c ON c.id = p.cliente_id
        JOIN pedidos_proveedor ped ON ped.id = a.pedido_id
        JOIN proveedores prov ON prov.id = ped.proveedor_id
        WHERE a.id=?''',(id,)).fetchone()
    factura = conn.execute('SELECT * FROM facturas WHERE albaran_id=?',(id,)).fetchone()
    conn.close()
    return render_template('albaran_detalle.html', albaran=albaran, factura=factura)

@app.route('/albaran/<int:id>/editar', methods=['POST'])
def albaran_editar(id):
    conn = get_db()
    conn.execute('UPDATE albaranes SET conformidad=?, notas=? WHERE id=?',
        (request.form['conformidad'], request.form.get('notas',''), id))
    conn.commit()
    conn.close()
    return redirect(url_for('albaran_detalle', id=id))

@app.route('/albaran/<int:id>/facturar', methods=['POST'])
def albaran_facturar(id):
    conn = get_db()
    alb = conn.execute('''SELECT a.*, p.cliente_id, p.importe as proyecto_importe, p.nombre as proyecto_nombre
        FROM albaranes a JOIN proyectos p ON p.id=a.proyecto_id WHERE a.id=?''',(id,)).fetchone()
    
    # Create factura from albaran
    num_fac = next_num('facturas','numero','FAC')
    conn.execute('''INSERT INTO facturas 
        (cliente_id, proyecto_id, albaran_id, numero, concepto, base, iva, irpf, estado, fecha_emision, fecha_vencimiento)
        VALUES (?,?,?,?,?,?,?,?,?,date('now'),date('now','+30 days'))''',
        (alb['cliente_id'], alb['proyecto_id'], id, num_fac, 
         alb['proyecto_nombre'], alb['proyecto_importe'], 21, 15, 'pendiente'))
    
    # Mark albaran as facturado
    conn.execute("UPDATE albaranes SET estado='facturado' WHERE id=?",(id,))
    conn.commit()
    fac_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    
    return redirect(url_for('albaran_detalle', id=id))

# ── TEMPLATE GLOBALS ──────────────────────────────────────────────────────────
@app.context_processor
def inject_globals():
    return {
        'today': date.today().isoformat(),
        'now': datetime.now().strftime('%b %Y'),
        'request': request,
    }

if __name__ == '__main__':
    init_db()
    print("\n✓ JA·ERP iniciado → http://localhost:5000\n")
    app.run(debug=True, host='0.0.0.0', port=5000)
