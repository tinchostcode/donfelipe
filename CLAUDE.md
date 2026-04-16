# Don Felipe — Pescadería · Contexto del proyecto (v3)

> Última actualización: abril 2026

---

## 1. Stack tecnológico

| Capa | Tecnología |
|------|-----------|
| Frontend | HTML5 + CSS3 + JavaScript vanilla (single file `index.html`) |
| Gráficos | Chart.js 4.4.1 (cdnjs.cloudflare.com) |
| Backend | Python 3 + Flask |
| Base de datos | PostgreSQL |
| Auth | Sesiones Flask server-side |
| Pagos | Mercado Pago SDK — Checkout Pro |
| IA | Claude Haiku (`claude-haiku-4-5-20251001`) — proxy backend |
| Deploy | Local Windows / Railway / Render |

---

## 2. Archivos

```
donfelipe/
├── index.html        # App completa: UI + lógica JS
├── server.py         # Backend Flask: auth, roles, API REST
├── schema.sql        # Tablas + migraciones IF NOT EXISTS
├── requirements.txt  # flask, psycopg2-binary, mercadopago, gunicorn
├── Procfile          # python server.py
└── CLAUDE.md         # Este archivo
```

---

## 3. Variables de entorno

```bash
DATABASE_URL=postgresql://user:pass@host:5432/dbname
SECRET_KEY=clave-larga
ANTHROPIC_API_KEY=sk-ant-...   # Claude Haiku para IA
MP_ACCESS_TOKEN=APP_USR-...    # opcional
PRODUCTION=1                    # cookies seguras en https
```

---

## 4. Arranque local (Windows)

```bat
@echo off
set DATABASE_URL=postgresql://postgres:PASSWORD@localhost:5432/donfelipe
set SECRET_KEY=donfelipe-local-2026
set ANTHROPIC_API_KEY=sk-ant-XXXXXXXXXX
python server.py
pause
```

Primera vez: `python server.py --setup` → crea tablas + admin/don.felipe

`run_migrations()` corre siempre al arrancar y aplica todos los ALTER TABLE sin perder datos.

---

## 5. Módulos implementados

- **Dashboard**: KPIs, gráficos 7d, tendencia 3 meses, top5, proyección stock, alertas, banner pedidos próximos
- **Caja**: ventas, búsqueda, anulación (admin), estado facturación (Pendiente/Facturada), cierre imprimible, MP
- **Stock**: lotes, vencimientos, catálogo con unidades (kg/unidad/litro/gramo) e indicador stock reservado
- **Merma**: registro, gráficos, historial costos
- **Pedidos**: hora de entrega 24hs, alerta configurable, reserva de stock, entrega con venta automática
- **Clientes**: historial acumulado
- **Rentabilidad**: selector 30/60/90 días, margen por producto
- **Reportes**: reporte mensual imprimible, top5, mejor día, desglose pagos
- **Asistente IA**: Claude Haiku, system prompt pescadería/finanzas, contexto en tiempo real
- **Config**: logo, nombre, MP, usuarios, permisos vendedor
- **Backup**: JSON completo + CSV para Excel, aviso si > 7 días
- **Notas**: botón flotante 📝, por usuario, abre al login si hay pendientes
- **Screensaver**: peces animados tras 60s de inactividad

---

## 6. Roles

**Admin**: acceso total, anulaciones, config, backup, notas propias.
**Vendedor**: solo secciones habilitadas (default: Caja + Pedidos). Sin Settings.

---

## 7. API endpoints

```
Auth:       POST /api/auth/login|logout   GET /api/auth/me
Config:     GET|PUT /api/config           POST /api/config/logo
Usuarios:   GET|POST /api/usuarios        PUT|DELETE /api/usuarios/:id
            POST /api/usuarios/cambiar-password
Permisos:   GET|PUT /api/permisos
Productos:  GET|POST /api/productos       PUT|DELETE /api/productos/:id
Clientes:   GET|POST /api/clientes
Ventas:     GET /api/ventas?fecha=        POST /api/ventas
            GET /api/ventas/rango?dias=   POST /api/ventas/:id/anular
            PUT /api/ventas/:id/factura
Lotes:      GET|POST /api/lotes           DELETE /api/lotes/:id
Mermas:     GET|POST /api/mermas
Pedidos:    GET|POST /api/pedidos         PUT|DELETE /api/pedidos/:id
            GET /api/pedidos/alertas
Dashboard:  GET /api/dashboard
Reportes:   GET /api/reportes/tendencia
            GET /api/reportes/mensual?mes=YYYY-MM
            GET /api/reportes/rango?desde=&hasta=
Backup:     GET /api/backup
IA:         POST /api/ia/chat
MP:         POST /api/mp/crear-preferencia
Notas:      GET|POST /api/notas           PUT|DELETE /api/notas/:id
            DELETE /api/notas/limpiar
Hist:       GET /api/hist-costos
```

---

## 8. Schema BD — columnas clave

```
productos:  unidad (kg/unidad/litro/gramo), stock_reservado
ventas:     estado_factura (pendiente/facturada), anulada, motivo_anulacion
pedidos:    hora_ent (TIME), alerta_horas (INTEGER default 2)
notas:      usuario_id, texto, completada, creada_en
```

**Todas las columnas nuevas se agregan en `run_migrations()` con `IF NOT EXISTS`.**

---

## 9. Reglas de desarrollo

- Single-file frontend: todo en `index.html`. Sin CSS/JS separados.
- Sin frameworks: vanilla + Chart.js.
- Todo en español argentino.
- Al agregar columna: agregarla en `run_migrations()` Y en `schema.sql`.
- Toda operación que modifica datos: `await` en el `onOk` del confirmar.
- Fechas: `String(fecha).slice(0,10)` → `YYYY-MM-DD`. Display con `fmtFecha()` → `DD/MM/YYYY`.
- Horas: siempre 24hs. Input de hora como `type="text"` con `formatHora()` (no `type="time"` — Windows muestra AM/PM).
- `serialize_row()` en todos los endpoints — no usar `jsonify(list(rows))` directo.
- `isMobile()` = `window.innerWidth < 768`.

---

## 10. Backlog

- [ ] Impresión de etiquetas (código + fecha vencimiento)
- [ ] Proveedores como entidad (teléfono, CUIT, historial)
- [ ] Cuenta corriente / fiado
- [ ] PWA instalable
- [ ] Facturación electrónica AFIP
- [ ] Alertas por WhatsApp
- [ ] Multi-sucursal
