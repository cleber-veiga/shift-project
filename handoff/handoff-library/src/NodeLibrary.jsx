/* NodeLibrary — painel lateral de seleção e drag-and-drop de nodes */
const { useState: useLibState, useMemo: useLibMemo, useEffect: useLibEffect, useRef: useLibRef } = React;

/* ------------- mini preview dos 26 nodes (body glanceable fake) ------------- */
/* Cada entry recebe {tone} e renderiza um body minúsculo e fiel ao real node. */
function MiniBody({ type }) {
  const mono = 'mono text-[9px] leading-[1.3]';
  const chip = (bg, txt, label) => (
    <span className="px-1 py-[1px] rounded mono text-[8px] font-semibold" style={{ background: bg, color: txt }}>{label}</span>
  );

  switch (type) {
    case 'cron':
      return <div className={`${mono} text-slate-700`}>0 */4 * * *</div>;
    case 'webhook':
      return <div className="flex items-center gap-1">{chip('#dcfce7','#166534','POST')}<span className={`${mono} text-slate-600 truncate`}>/api/orders</span></div>;
    case 'manual':
      return <div className="flex items-center gap-1 text-[9px] text-slate-500"><Icon name="MousePointerClick" size={10}/> Aguardando</div>;
    case 'subTrigger':
      return <div className="text-[9px] text-slate-500">Fluxo pai · 3 inputs</div>;
    case 'queue':
      return <div className="flex items-center gap-1">{chip('#fef3c7','#92400e','KAFKA')}<span className={`${mono} text-slate-600 truncate`}>orders.v1</span></div>;
    case 'http':
      return <div className="flex items-center gap-1">{chip('#dbeafe','#1e40af','GET')}<span className={`${mono} text-slate-600 truncate`}>api.stripe.co…</span></div>;
    case 'sql':
      return <div className="rounded-[4px] bg-slate-900 px-1.5 py-1 mono text-[8px] leading-tight"><span className="text-pink-400">SELECT</span> <span className="text-slate-300">*</span></div>;
    case 'email':
      return <div className={`${mono} text-slate-600 truncate`}>→ {'{{email}}'}</div>;
    case 'execSub':
      return <div className="flex items-center gap-1"><span className="text-[9px] text-slate-600 truncate">checkout_v2</span>{chip('#e0e7ff','#3730a3','sync')}</div>;
    case 'nosql':
      return <div className={`${mono} text-slate-600 truncate`}>db.logs.insert()</div>;
    case 'if':
      return <div className={`${mono} text-slate-700 truncate`}>{'{{val}} > 1000'}</div>;
    case 'switch':
      return <div className="flex gap-0.5">{['R1','R2','D'].map(r=><span key={r} className="px-1 rounded bg-orange-100 text-orange-700 mono text-[8px]">{r}</span>)}</div>;
    case 'loop':
      return <div className={`${mono} text-slate-600 truncate`}>∀ {'{{items}}'}</div>;
    case 'merge':
      return <div className="text-[9px] text-slate-500">2 entradas → 1</div>;
    case 'errorCatch':
      return <div className="flex items-center gap-1 text-[9px] text-rose-600"><Icon name="TriangleAlert" size={10}/> on error</div>;
    case 'wait':
      return <div className="flex items-center gap-1"><span className="text-[9px] text-slate-600">15 min</span><span className="flex-1 h-[3px] rounded-full bg-orange-100 overflow-hidden"><span className="block h-full w-2/3 bg-orange-400"/></span></div>;
    case 'mapper':
      return <div className={`${mono} text-slate-600 truncate`}>name → {'{{n}}'}</div>;
    case 'code':
      return <div className="rounded-[4px] bg-slate-900 px-1.5 py-1 mono text-[8px] leading-tight"><span className="text-purple-400">const</span> <span className="text-cyan-300">x</span></div>;
    case 'datetime':
      return <div className={`${mono} text-slate-600 truncate text-[8.5px]`}>ISO → DD/MM/YYYY</div>;
    case 'conv':
      return <div className="flex items-center gap-0.5 mono text-[8px]">{chip('#ecfeff','#155e75','CSV')}→{chip('#ecfeff','#155e75','JSON')}</div>;
    case 'state':
      return <div className={`${mono} text-slate-600 truncate`}>last_id = {'{{id}}'}</div>;
    case 'file':
      return <div className={`${mono} text-slate-600 truncate`}>/var/data.csv</div>;
    case 'llm':
      return <div className="flex items-center gap-1">{chip('#fce7f3','#9f1239','GPT-4')}<span className="text-[9px] text-slate-500 truncate italic">"resuma…"</span></div>;
    case 'mem':
      return <div className="text-[9px] text-slate-600">Buffer: 20 msgs</div>;
    case 'vector':
      return <div className="flex items-center gap-1 text-[9px]"><span className="text-slate-500">Pinecone</span><span className="text-slate-400 truncate">· query</span></div>;
    case 'agent':
      return <div className="flex gap-0.5">{['SQL','WEB','MAIL'].map(t=><span key={t} className="px-1 rounded bg-pink-100 text-pink-700 mono text-[8px]">{t}</span>)}</div>;
    default:
      return <div className="text-[9px] text-slate-400">—</div>;
  }
}

/* ------------- preview card: mini-replica do CanvasNode ------------- */
function NodeLibCard({ meta, onAdd, onDragStart }) {
  const t = TONES[meta.group];
  const [hover, setHover] = useLibState(false);

  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = 'copy';
        e.dataTransfer.setData('application/x-node-type', meta.type);
        onDragStart?.(meta.type);
      }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onDoubleClick={() => onAdd(meta.type)}
      className="lib-card group"
      style={{
        '--tone-dot': t.dot,
        '--tone-glow': t.glow,
        '--tone-ring': t.tileRing,
      }}
      title={`${meta.label} — arraste para o canvas ou duplo-clique para adicionar`}
    >
      <div className="lib-card-accent" style={{ background: `linear-gradient(135deg, ${t.dot} 0%, ${t.dot} 40%, transparent 70%)` }} />

      {/* header mimic */}
      <div className="flex items-start gap-2 px-2.5 pt-2.5 pb-1.5 relative z-10">
        <div className="lib-icon-tile" style={{ background: t.tile, color: t.ink, boxShadow: `inset 0 0 0 1px ${t.tileRing}` }}>
          <Icon name={meta.icon} size={13} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[11.5px] font-semibold text-slate-800 leading-tight truncate">{meta.label}</div>
          <div className="mono text-[9px] text-slate-400 leading-tight mt-0.5 truncate">{meta.type}</div>
        </div>
        <button
          onClick={(e) => { e.stopPropagation(); onAdd(meta.type); }}
          className="lib-add-btn"
          title="Add to canvas"
        >
          <Icon name="Plus" size={11} />
        </button>
      </div>

      {/* mini body */}
      <div className="mx-2 mb-2 rounded-[8px] px-2 py-1.5 relative z-10"
           style={{ background:'linear-gradient(180deg, rgba(248,250,252,0.9), rgba(241,245,249,0.75))', border:'1px solid rgba(15,23,42,0.05)' }}>
        <MiniBody type={meta.type} />
      </div>

      {/* hover desc */}
      <div className="lib-desc" style={{ opacity: hover ? 1 : 0 }}>{meta.desc}</div>
    </div>
  );
}

/* ------------- drawer principal ------------- */
function NodeLibrary({ open, onClose, onAdd, onDragStart }) {
  const [query, setQuery] = useLibState('');
  const [activeGroups, setActiveGroups] = useLibState(() => new Set(Object.keys(TONES)));
  const [layout, setLayout] = useLibState('grid'); // grid | list
  const inputRef = useLibRef(null);

  useLibEffect(() => { if (open) setTimeout(() => inputRef.current?.focus(), 50); }, [open]);

  const toggleGroup = (g) => {
    setActiveGroups(s => {
      const next = new Set(s);
      if (next.size === Object.keys(TONES).length) { next.clear(); next.add(g); return next; }
      next.has(g) ? next.delete(g) : next.add(g);
      if (next.size === 0) return new Set(Object.keys(TONES));
      return next;
    });
  };
  const resetGroups = () => setActiveGroups(new Set(Object.keys(TONES)));

  const filtered = useLibMemo(() => {
    const q = query.toLowerCase().trim();
    return NODE_META.filter(m => {
      if (!activeGroups.has(m.group)) return false;
      if (!q) return true;
      if (m.label.toLowerCase().includes(q)) return true;
      if (m.type.toLowerCase().includes(q)) return true;
      if (m.desc.toLowerCase().includes(q)) return true;
      if (m.tags?.some(t => t.toLowerCase().includes(q))) return true;
      return false;
    });
  }, [query, activeGroups]);

  const grouped = useLibMemo(() => {
    const out = {};
    filtered.forEach(m => { (out[m.group] = out[m.group] || []).push(m); });
    return out;
  }, [filtered]);

  const totalCount = NODE_META.length;
  const shownCount = filtered.length;

  return (
    <>
      {/* FAB to open */}
      {!open && (
        <button onClick={() => onClose(false)} className="lib-fab" title="Abrir biblioteca de nodes">
          <Icon name="LayoutGrid" size={16} />
          <span className="text-[11.5px] font-medium">Library</span>
          <kbd className="mono text-[9.5px] bg-white/15 px-1.5 py-0.5 rounded">L</kbd>
        </button>
      )}

      {/* Drawer */}
      <div className={`lib-drawer ${open ? 'lib-drawer--open' : ''}`} aria-hidden={!open}>
        {/* header */}
        <div className="lib-header">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-slate-800 to-slate-900 text-white flex items-center justify-center">
              <Icon name="LayoutGrid" size={14} />
            </div>
            <div>
              <div className="text-[13px] font-semibold text-slate-800 leading-none">Node Library</div>
              <div className="text-[10.5px] text-slate-500 mt-0.5">{shownCount} of {totalCount} types</div>
            </div>
          </div>
          <div className="flex-1" />
          <div className="lib-layout-toggle">
            <button onClick={() => setLayout('grid')} className={layout==='grid' ? 'active':''} title="Grid view"><Icon name="LayoutGrid" size={12}/></button>
            <button onClick={() => setLayout('list')} className={layout==='list' ? 'active':''} title="List view"><Icon name="List" size={12}/></button>
          </div>
          <button onClick={() => onClose(true)} className="lib-close" title="Fechar"><Icon name="X" size={14}/></button>
        </div>

        {/* search */}
        <div className="lib-search">
          <Icon name="Search" size={14} className="text-slate-400" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Buscar por nome, tipo, tag…"
            className="flex-1 outline-none bg-transparent text-[13px] text-slate-800 placeholder:text-slate-400"
          />
          {query && (
            <button onClick={() => setQuery('')} className="text-slate-400 hover:text-slate-600"><Icon name="X" size={12}/></button>
          )}
        </div>

        {/* group filter chips */}
        <div className="lib-groups">
          {Object.entries(TONES).map(([key, t]) => {
            const active = activeGroups.has(key);
            const count = NODE_META.filter(m => m.group === key).length;
            return (
              <button
                key={key}
                onClick={() => toggleGroup(key)}
                className={`lib-group-chip ${active ? 'lib-group-chip--active' : ''}`}
                style={active ? { background: t.tile, color: t.ink, borderColor: t.tileRing } : {}}
              >
                <span className="w-1.5 h-1.5 rounded-full" style={{ background: t.dot }} />
                {t.name}
                <span className="lib-group-count">{count}</span>
              </button>
            );
          })}
          {activeGroups.size < Object.keys(TONES).length && (
            <button onClick={resetGroups} className="lib-group-chip lib-group-chip--reset">
              <Icon name="RotateCcw" size={10}/> Reset
            </button>
          )}
        </div>

        {/* list */}
        <div className={`lib-body ${layout === 'grid' ? 'lib-body--grid' : 'lib-body--list'}`}>
          {shownCount === 0 && (
            <div className="lib-empty">
              <div className="w-10 h-10 rounded-full bg-slate-100 flex items-center justify-center mb-2">
                <Icon name="SearchX" size={18} className="text-slate-400" />
              </div>
              <div className="text-[12.5px] text-slate-600 font-medium">Nenhum node encontrado</div>
              <div className="text-[11px] text-slate-400 mt-0.5">Tente outra busca ou reative grupos</div>
            </div>
          )}

          {Object.entries(grouped).map(([groupKey, items]) => {
            const t = TONES[groupKey];
            return (
              <div key={groupKey} className="lib-group-block">
                <div className="lib-group-header">
                  <span className="w-2 h-2 rounded-full" style={{ background: t.dot }} />
                  <span className={`text-[10px] font-semibold uppercase tracking-[0.16em] ${t.head}`}>{t.name}</span>
                  <span className="text-[10px] text-slate-400 font-normal">{items.length}</span>
                  <div className="flex-1 h-px bg-slate-200/70 ml-1" />
                </div>

                {layout === 'grid' ? (
                  <div className="lib-grid">
                    {items.map(m => (
                      <NodeLibCard key={m.type} meta={m} onAdd={(type) => { onAdd(type); }} onDragStart={onDragStart} />
                    ))}
                  </div>
                ) : (
                  <div className="lib-list">
                    {items.map(m => (
                      <div
                        key={m.type}
                        draggable
                        onDragStart={(e) => { e.dataTransfer.effectAllowed='copy'; e.dataTransfer.setData('application/x-node-type', m.type); onDragStart?.(m.type); }}
                        onDoubleClick={() => onAdd(m.type)}
                        className="lib-list-row"
                        style={{ '--tone-dot': TONES[m.group].dot }}
                      >
                        <div className="lib-icon-tile lib-icon-tile--sm" style={{ background: TONES[m.group].tile, color: TONES[m.group].ink, boxShadow:`inset 0 0 0 1px ${TONES[m.group].tileRing}` }}>
                          <Icon name={m.icon} size={12}/>
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="text-[12px] font-semibold text-slate-800 leading-tight truncate">{m.label}</div>
                          <div className="text-[10.5px] text-slate-500 leading-tight truncate">{m.desc}</div>
                        </div>
                        <button
                          onClick={(e) => { e.stopPropagation(); onAdd(m.type); }}
                          className="lib-add-btn lib-add-btn--sm"
                        ><Icon name="Plus" size={11}/></button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* footer */}
        <div className="lib-footer">
          <div className="flex items-center gap-1.5">
            <Icon name="Hand" size={11} className="text-slate-400" />
            <span>Arraste pro canvas</span>
          </div>
          <span className="text-slate-300">·</span>
          <div className="flex items-center gap-1.5">
            <Icon name="MousePointer2" size={11} className="text-slate-400" />
            <span>Duplo-clique para adicionar</span>
          </div>
          <div className="flex-1" />
          <kbd className="mono text-[9.5px] bg-slate-100 px-1.5 py-0.5 rounded">L</kbd>
          <span>toggle</span>
        </div>
      </div>
    </>
  );
}

window.NodeLibrary = NodeLibrary;
