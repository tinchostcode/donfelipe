-- Don Felipe — Pescadería
-- Schema PostgreSQL
-- Ejecutar una vez al inicializar la base de datos

-- Usuarios y auth
CREATE TABLE IF NOT EXISTS usuarios (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    pass_hash TEXT NOT NULL,
    rol VARCHAR(20) NOT NULL DEFAULT 'vendedor',  -- 'admin' | 'vendedor'
    nombre_display VARCHAR(100),
    activo BOOLEAN DEFAULT TRUE,
    creado_en TIMESTAMP DEFAULT NOW()
);

-- Permisos configurables por el admin para rol vendedor
-- Cada fila = una sección habilitada para vendedores
CREATE TABLE IF NOT EXISTS permisos_vendedor (
    id SERIAL PRIMARY KEY,
    seccion VARCHAR(50) UNIQUE NOT NULL,  -- 'caja', 'pedidos', 'stock', 'merma', 'clientes'
    habilitado BOOLEAN DEFAULT FALSE
);

-- Insertar permisos default para vendedor
INSERT INTO permisos_vendedor (seccion, habilitado) VALUES
    ('caja',          TRUE),
    ('pedidos',       TRUE),
    ('stock',         FALSE),
    ('merma',         FALSE),
    ('clientes',      FALSE),
    ('rentabilidad',  FALSE),
    ('ia',            FALSE)
ON CONFLICT (seccion) DO NOTHING;

-- Config general del negocio
CREATE TABLE IF NOT EXISTS config (
    clave VARCHAR(50) PRIMARY KEY,
    valor TEXT
);

INSERT INTO config (clave, valor) VALUES
    ('nombre',    'Don Felipe'),
    ('mp_token',  ''),
    ('mp_cuotas', '1'),
    ('logo',      '')
ON CONFLICT (clave) DO NOTHING;

-- Productos
CREATE TABLE IF NOT EXISTS productos (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    cat VARCHAR(50) DEFAULT 'Pescados',
    codigo VARCHAR(20) DEFAULT '',
    stock NUMERIC(10,2) DEFAULT 0,
    min_stock NUMERIC(10,2) DEFAULT 5,
    costo NUMERIC(12,2) DEFAULT 0,
    precio NUMERIC(12,2) DEFAULT 0,
    activo BOOLEAN DEFAULT TRUE,
    creado_en TIMESTAMP DEFAULT NOW()
);

-- Clientes
CREATE TABLE IF NOT EXISTS clientes (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    tel VARCHAR(30) DEFAULT '',
    email VARCHAR(100) DEFAULT '',
    dir VARCHAR(200) DEFAULT '',
    compras INTEGER DEFAULT 0,
    total NUMERIC(14,2) DEFAULT 0,
    creado_en TIMESTAMP DEFAULT NOW()
);

-- Lotes de ingreso
CREATE TABLE IF NOT EXISTS lotes (
    id SERIAL PRIMARY KEY,
    prod_id INTEGER REFERENCES productos(id) ON DELETE CASCADE,
    prod_nombre VARCHAR(100),
    kg NUMERIC(10,2) NOT NULL,
    costo NUMERIC(12,2) DEFAULT 0,
    proveedor VARCHAR(100) DEFAULT '',
    fecha_in DATE,
    fecha_venc DATE,
    nota TEXT DEFAULT '',
    creado_en TIMESTAMP DEFAULT NOW()
);

-- Ventas (cabecera)
CREATE TABLE IF NOT EXISTS ventas (
    id SERIAL PRIMARY KEY,
    fecha DATE NOT NULL DEFAULT CURRENT_DATE,
    hora TIME NOT NULL DEFAULT CURRENT_TIME,
    cliente VARCHAR(100) DEFAULT 'Mostrador',
    total NUMERIC(14,2) NOT NULL,
    pago VARCHAR(30) NOT NULL DEFAULT 'efectivo',
    usuario_id INTEGER REFERENCES usuarios(id),
    creado_en TIMESTAMP DEFAULT NOW()
);

-- Items de cada venta
CREATE TABLE IF NOT EXISTS venta_items (
    id SERIAL PRIMARY KEY,
    venta_id INTEGER REFERENCES ventas(id) ON DELETE CASCADE,
    prod_id INTEGER REFERENCES productos(id),
    prod_nombre VARCHAR(100),
    kg NUMERIC(10,2),
    precio NUMERIC(12,2),
    subtotal NUMERIC(14,2),
    cat VARCHAR(50)
);

-- Pedidos
CREATE TABLE IF NOT EXISTS pedidos (
    id SERIAL PRIMARY KEY,
    cliente VARCHAR(100) NOT NULL,
    fecha_ent DATE NOT NULL,
    total NUMERIC(14,2) DEFAULT 0,
    notas TEXT DEFAULT '',
    estado VARCHAR(20) DEFAULT 'pendiente',
    usuario_id INTEGER REFERENCES usuarios(id),
    creado_en TIMESTAMP DEFAULT NOW()
);

-- Items de cada pedido
CREATE TABLE IF NOT EXISTS pedido_items (
    id SERIAL PRIMARY KEY,
    pedido_id INTEGER REFERENCES pedidos(id) ON DELETE CASCADE,
    prod_id INTEGER REFERENCES productos(id),
    prod_nombre VARCHAR(100),
    kg NUMERIC(10,2),
    precio NUMERIC(12,2),
    subtotal NUMERIC(14,2)
);

-- Mermas
CREATE TABLE IF NOT EXISTS mermas (
    id SERIAL PRIMARY KEY,
    prod_id INTEGER REFERENCES productos(id),
    prod_nombre VARCHAR(100),
    kg NUMERIC(10,2) NOT NULL,
    costo NUMERIC(12,2) DEFAULT 0,
    fecha DATE NOT NULL DEFAULT CURRENT_DATE,
    motivo VARCHAR(50) DEFAULT 'otro',
    obs TEXT DEFAULT '',
    usuario_id INTEGER REFERENCES usuarios(id),
    creado_en TIMESTAMP DEFAULT NOW()
);

-- Historial de costos (para rentabilidad)
CREATE TABLE IF NOT EXISTS hist_costos (
    id SERIAL PRIMARY KEY,
    prod_id INTEGER REFERENCES productos(id),
    prod_nombre VARCHAR(100),
    fecha DATE NOT NULL DEFAULT CURRENT_DATE,
    costo NUMERIC(12,2),
    precio_venta NUMERIC(12,2)
);

-- Unidad de venta en productos
ALTER TABLE productos ADD COLUMN IF NOT EXISTS unidad VARCHAR(20) DEFAULT 'kg';

-- Estado de facturación en ventas
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS estado_factura VARCHAR(20) DEFAULT 'pendiente';

-- Notas/recordatorios por usuario
CREATE TABLE IF NOT EXISTS notas (
    id SERIAL PRIMARY KEY,
    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
    texto TEXT NOT NULL,
    completada BOOLEAN DEFAULT FALSE,
    creada_en TIMESTAMP DEFAULT NOW()
);

-- Columnas de hora de entrega y alerta en pedidos
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS hora_ent    TIME DEFAULT NULL;
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS alerta_horas INTEGER DEFAULT 2;

-- Stock reservado en productos
ALTER TABLE productos ADD COLUMN IF NOT EXISTS stock_reservado NUMERIC(10,2) DEFAULT 0;

-- Columnas de anulación en ventas
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS anulada     BOOLEAN   DEFAULT FALSE;
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS anulada_en  TIMESTAMP DEFAULT NULL;
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS anulada_por INTEGER   REFERENCES usuarios(id);
ALTER TABLE ventas ADD COLUMN IF NOT EXISTS motivo_anulacion TEXT DEFAULT NULL;

-- Índices de performance
CREATE INDEX IF NOT EXISTS idx_ventas_fecha    ON ventas(fecha);
CREATE INDEX IF NOT EXISTS idx_lotes_prod      ON lotes(prod_id);
CREATE INDEX IF NOT EXISTS idx_mermas_fecha    ON mermas(fecha);
CREATE INDEX IF NOT EXISTS idx_venta_items_vid ON venta_items(venta_id);
