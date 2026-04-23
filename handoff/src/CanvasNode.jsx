/* Base: TONES, Icon, Badge, KV, CanvasNode that uses React Flow <Handle> */
const { useState, useEffect, useRef, useCallback, useMemo } = React;

/* ---- Color tokens per group ---- */
const TONES = {
  purple:  { name:'Triggers',       head:'text-purple-700',  dot:'#a855f7', grad:'linear-gradient(135deg,#a855f7,#d946ef)', tile:'linear-gradient(180deg,#faf5ff,#f3e8ff)', tileRing:'rgba(168,85,247,.25)', ink:'#6b21a8', glow:'glow-purple',  aura:'aura-purple' },
  emerald: { name:'Actions',        head:'text-emerald-700', dot:'#10b981', grad:'linear-gradient(135deg,#10b981,#14b8a6)', tile:'linear-gradient(180deg,#ecfdf5,#d1fae5)', tileRing:'rgba(16,185,129,.25)',  ink:'#065f46', glow:'glow-emerald', aura:'aura-emerald' },
  orange:  { name:'Logic',          head:'text-orange-700',  dot:'#f97316', grad:'linear-gradient(135deg,#f97316,#f59e0b)', tile:'linear-gradient(180deg,#fff7ed,#ffedd5)', tileRing:'rgba(249,115,22,.25)',  ink:'#9a3412', glow:'glow-orange',  aura:'aura-orange' },
  cyan:    { name:'Transformation', head:'text-cyan-700',    dot:'#06b6d4', grad:'linear-gradient(135deg,#06b6d4,#0ea5e9)', tile:'linear-gradient(180deg,#ecfeff,#cffafe)', tileRing:'rgba(6,182,212,.25)',   ink:'#155e75', glow:'glow-cyan',    aura:'aura-cyan' },
  slate:   { name:'Storage',        head:'text-slate-700',   dot:'#64748b', grad:'linear-gradient(135deg,#64748b,#475569)', tile:'linear-gradient(180deg,#f8fafc,#f1f5f9)', tileRing:'rgba(100,116,139,.25)', ink:'#334155', glow:'glow-slate',   aura:'aura-slate' },
  pink:    { name:'AI',             head:'text-pink-700',    dot:'#ec4899', grad:'linear-gradient(135deg,#ec4899,#f43f5e)', tile:'linear-gradient(180deg,#fdf2f8,#fce7f3)', tileRing:'rgba(236,72,153,.25)',  ink:'#9d174d', glow:'glow-pink',    aura:'aura-pink' },
};

/* ---- Lucide icon safe-getter ---- */
function Icon({ name, size = 14, className = '', style }) {
  const [, force] = useState(0);
  useEffect(() => {
    if (!window.Lucide) {
      const t = setInterval(() => { if (window.Lucide) { force(x => x + 1); clearInterval(t); } }, 60);
      return () => clearInterval(t);
    }
  }, []);
  const L = window.Lucide;
  if (!L) return <span style={{ display:'inline-block', width:size, height:size }} />;
  const Cmp = L[name] || L.Circle;
  return <Cmp size={size} className={className} style={style} strokeWidth={2} />;
}

function Badge({ children, tone='slate', solid=false, className='' }) {
  const map = {
    slate:   solid ? 'bg-slate-700 text-white'   : 'bg-slate-100 text-slate-700',
    purple:  solid ? 'bg-purple-600 text-white'  : 'bg-purple-100 text-purple-700',
    emerald: solid ? 'bg-emerald-600 text-white' : 'bg-emerald-100 text-emerald-700',
    orange:  solid ? 'bg-orange-500 text-white'  : 'bg-orange-100 text-orange-700',
    cyan:    solid ? 'bg-cyan-600 text-white'    : 'bg-cyan-100 text-cyan-700',
    pink:    solid ? 'bg-pink-600 text-white'    : 'bg-pink-100 text-pink-700',
    blue:    solid ? 'bg-blue-600 text-white'    : 'bg-blue-100 text-blue-700',
    green:   solid ? 'bg-green-600 text-white'   : 'bg-green-100 text-green-700',
    amber:   solid ? 'bg-amber-500 text-white'   : 'bg-amber-100 text-amber-800',
    rose:    solid ? 'bg-rose-600 text-white'    : 'bg-rose-100 text-rose-700',
  };
  return <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-[10px] font-semibold mono ${map[tone]} ${className}`}>{children}</span>;
}

function KV({ k, v }) {
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <span className="text-slate-400 mono">{k}</span>
      <span className="mono text-slate-700 truncate">{v}</span>
    </div>
  );
}

/* ---- Labeled React Flow Handle ---- */
function PortHandle({ type, id, top, color, label }) {
  const { Handle, Position } = window.ReactFlow;
  const pos = type === 'source' ? Position.Right : Position.Left;
  const isLeft = type === 'target';
  return (
    <>
      <Handle
        type={type}
        id={id}
        position={pos}
        className="rf-handle"
        style={{ top, borderColor: color }}
      />
      {label && (
        <span
          className="handle-label"
          style={{
            top,
            [isLeft ? 'left' : 'right']: 14,
            transform: 'translateY(-50%)',
          }}
        >
          {label}
        </span>
      )}
    </>
  );
}

/* ---- Base CanvasNode used by all 26 variants ---- */
function CanvasNode({
  id,
  data,
  selected,
  tone='purple',
  icon='Box',
  defaultTitle,
  subtitle,
  inputs = [],
  outputs = [],
  width = 260,
  children,
}) {
  const t = TONES[tone];

  // Pull live state from React Flow node data so external actions stay in sync
  const title    = data?.title ?? defaultTitle;
  const status   = data?.status ?? 'idle';
  const disabled = !!data?.disabled;
  const dupePulse = !!data?.dupePulse;

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(title);
  const [menuOpen, setMenuOpen] = useState(false);
  const inputRef = useRef(null);
  const menuRef = useRef(null);
  const btnRef = useRef(null);

  useEffect(() => { setDraft(title); }, [title]);
  useEffect(() => { if (editing) inputRef.current?.select(); }, [editing]);

  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (e) => {
      if (menuRef.current?.contains(e.target)) return;
      if (btnRef.current?.contains(e.target)) return;
      setMenuOpen(false);
    };
    const onKey = (e) => { if (e.key === 'Escape') setMenuOpen(false); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, [menuOpen]);

  const bus = window.__nodeBus;

  const commitTitle = () => {
    const v = (draft || '').trim() || title;
    bus?.updateNode(id, { title: v });
    setEditing(false);
  };
  const cancelEdit = () => { setDraft(title); setEditing(false); };
  const doRun       = () => { setMenuOpen(false); bus?.runNode(id); };
  const doToggle    = () => { setMenuOpen(false); bus?.toggleDisabled(id); };
  const doDuplicate = () => { setMenuOpen(false); bus?.duplicateNode(id); };
  const doRemove    = () => { setMenuOpen(false); bus?.removeNode(id); };

  const statusMeta =
    status === 'success' ? { label:'ok',       dot:'#10b981', text:'text-emerald-700' } :
    status === 'running' ? { label:'running',  dot:'#0ea5e9', text:'text-sky-700',   pulse:true } :
    status === 'error'   ? { label:'error',    dot:'#f43f5e', text:'text-rose-700'  } :
    disabled             ? { label:'disabled', dot:'#cbd5e1', text:'text-slate-500' } :
                           { label:'idle',     dot:'#cbd5e1', text:'text-slate-500' };

  const portTop = (i, n) => `${((i+1) * 100) / (n+1)}%`;

  const cssVars = {
    '--tone-grad': t.grad,
    '--tone-tile': t.tile,
    '--tone-tile-ring': t.tileRing,
    '--tone-ink': t.ink,
  };

  return (
    <div
      className={[
        'node', t.glow,
        selected ? 'selected' : '',
        disabled ? 'is-disabled' : '',
        status === 'running' ? 'is-running' : '',
        dupePulse ? 'ring-2 ring-offset-2 ring-blue-400' : '',
      ].join(' ')}
      style={{ width, ...cssVars }}
    >
      <div className={`aura ${t.aura}`} />
      <div className="corner" />

      {/* Header */}
      <div className="relative z-10 px-3.5 pt-3 pb-2.5 flex items-center gap-2.5">
        <div className="icon-tile"><Icon name={icon} size={15} /></div>
        <div className="min-w-0 flex-1">
          {editing ? (
            <input
              ref={inputRef}
              className="title-input text-[13px] font-semibold tracking-[-0.01em]"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commitTitle}
              onKeyDown={(e) => { if (e.key === 'Enter') commitTitle(); if (e.key === 'Escape') cancelEdit(); }}
              onMouseDown={(e) => e.stopPropagation()}
            />
          ) : (
            <div
              className="title-editable text-[13px] font-semibold text-slate-800 leading-tight truncate tracking-[-0.01em]"
              onDoubleClick={(e) => { e.stopPropagation(); setEditing(true); }}
              title="Double-click to rename"
            >
              {title}
            </div>
          )}
          {subtitle && <div className="text-[10.5px] text-slate-500 leading-tight truncate mono mt-0.5">{subtitle}</div>}
        </div>
        <div className="flex items-center gap-1">
          <span className="status-chip">
            <span className={`status-dot ${statusMeta.pulse ? 'pulse-ring' : ''}`} style={{ background: statusMeta.dot }} />
            <span className={statusMeta.text}>{statusMeta.label}</span>
          </span>
          <button
            ref={btnRef}
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => { e.stopPropagation(); setMenuOpen(o => !o); }}
            className={`icon-btn nodrag ${menuOpen ? 'active' : ''}`}
            aria-label="Node actions"
          >
            <Icon name="MoreHorizontal" size={14} />
          </button>
        </div>
      </div>

      {/* Menu */}
      {menuOpen && (
        <div ref={menuRef} className="node-menu nodrag" onMouseDown={(e) => e.stopPropagation()} onClick={(e) => e.stopPropagation()}>
          <button onClick={() => { setEditing(true); setMenuOpen(false); }}>
            <Icon name="Pencil" size={13} /> Rename <kbd>F2</kbd>
          </button>
          <button onClick={doRun} disabled={disabled}>
            <Icon name="Play" size={13} /> Run node <kbd>⌘R</kbd>
          </button>
          <button onClick={doToggle}>
            <Icon name={disabled ? 'Power' : 'PowerOff'} size={13} />
            {disabled ? 'Enable' : 'Disable'}
          </button>
          <button onClick={doDuplicate}>
            <Icon name="Copy" size={13} /> Duplicate <kbd>⌘D</kbd>
          </button>
          <div className="sep" />
          <button className="danger" onClick={doRemove}>
            <Icon name="Trash2" size={13} /> Remove <kbd>⌫</kbd>
          </button>
        </div>
      )}

      <div className="relative z-10 mx-3 h-px bg-gradient-to-r from-transparent via-slate-200 to-transparent" />

      <div className="relative z-10 mx-3 mb-3 mt-1 body-surface px-3 py-2.5 nodrag">
        {children}
      </div>

      {/* Handles */}
      {inputs.map((p, i) => (
        <PortHandle key={`in-${p.id}`} type="target" id={p.id} top={portTop(i, inputs.length)} color={t.dot} label={p.label} />
      ))}
      {outputs.map((p, i) => (
        <PortHandle key={`out-${p.id}`} type="source" id={p.id} top={portTop(i, outputs.length)} color={t.dot} label={p.label} />
      ))}
    </div>
  );
}

Object.assign(window, { TONES, Icon, Badge, KV, CanvasNode, PortHandle });
