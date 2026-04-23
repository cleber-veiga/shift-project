/**
 * Design tokens para o Workflow Canvas.
 * Fonte da verdade — o CSS em `workflow-nodes.css` espelha esses valores.
 */

export type Tone = 'purple' | 'emerald' | 'orange' | 'cyan' | 'slate' | 'pink';

export interface ToneDef {
  /** Nome curto do grupo, ex: "Triggers" */
  label: string;
  /** Cor sólida principal (hex), usada em ícones, handles e glow */
  solid: string;
  /** Cor suave para backgrounds e tiles (hex com alpha baixo) */
  soft: string;
  /** Cor do glow no hover (rgba com alpha médio) */
  glow: string;
  /** Cor do corner-accent (gradient top-left do card) */
  accent: string;
  /** Classe Tailwind do text-color principal (text-{color}-600) */
  textClass: string;
  /** Classe Tailwind do bg suave (bg-{color}-50) */
  bgSoftClass: string;
  /** Classe Tailwind do ring de hover (ring-{color}-400/40) */
  ringClass: string;
}

export const TONES: Record<Tone, ToneDef> = {
  purple: {
    label: 'Triggers',
    solid: '#9333ea',
    soft: '#f5f3ff',
    glow: 'rgba(147, 51, 234, 0.20)',
    accent: 'linear-gradient(135deg, #c084fc 0%, #9333ea 60%, transparent 60%)',
    textClass: 'text-purple-600',
    bgSoftClass: 'bg-purple-50',
    ringClass: 'ring-purple-400/40',
  },
  emerald: {
    label: 'Actions',
    solid: '#059669',
    soft: '#ecfdf5',
    glow: 'rgba(5, 150, 105, 0.20)',
    accent: 'linear-gradient(135deg, #6ee7b7 0%, #059669 60%, transparent 60%)',
    textClass: 'text-emerald-600',
    bgSoftClass: 'bg-emerald-50',
    ringClass: 'ring-emerald-400/40',
  },
  orange: {
    label: 'Logic',
    solid: '#ea580c',
    soft: '#fff7ed',
    glow: 'rgba(234, 88, 12, 0.20)',
    accent: 'linear-gradient(135deg, #fdba74 0%, #ea580c 60%, transparent 60%)',
    textClass: 'text-orange-600',
    bgSoftClass: 'bg-orange-50',
    ringClass: 'ring-orange-400/40',
  },
  cyan: {
    label: 'Transformation',
    solid: '#0891b2',
    soft: '#ecfeff',
    glow: 'rgba(8, 145, 178, 0.20)',
    accent: 'linear-gradient(135deg, #67e8f9 0%, #0891b2 60%, transparent 60%)',
    textClass: 'text-cyan-600',
    bgSoftClass: 'bg-cyan-50',
    ringClass: 'ring-cyan-400/40',
  },
  slate: {
    label: 'Storage',
    solid: '#475569',
    soft: '#f8fafc',
    glow: 'rgba(71, 85, 105, 0.20)',
    accent: 'linear-gradient(135deg, #94a3b8 0%, #475569 60%, transparent 60%)',
    textClass: 'text-slate-600',
    bgSoftClass: 'bg-slate-50',
    ringClass: 'ring-slate-400/40',
  },
  pink: {
    label: 'AI',
    solid: '#db2777',
    soft: '#fdf2f8',
    glow: 'rgba(219, 39, 119, 0.20)',
    accent: 'linear-gradient(135deg, #f9a8d4 0%, #db2777 60%, transparent 60%)',
    textClass: 'text-pink-600',
    bgSoftClass: 'bg-pink-50',
    ringClass: 'ring-pink-400/40',
  },
};

/** Status chip colors */
export const STATUS = {
  idle: { dot: '#cbd5e1', text: 'text-slate-500', bg: 'bg-slate-100', label: 'idle' },
  running: { dot: '#3b82f6', text: 'text-blue-600', bg: 'bg-blue-50', label: 'running' },
  ok: { dot: '#10b981', text: 'text-emerald-600', bg: 'bg-emerald-50', label: 'ok' },
  error: { dot: '#ef4444', text: 'text-red-600', bg: 'bg-red-50', label: 'error' },
  disabled: { dot: '#94a3b8', text: 'text-slate-400', bg: 'bg-slate-100', label: 'disabled' },
} as const;

/** Dimensões do node base (em px) */
export const NODE_DIMS = {
  minWidth: 240,
  maxWidth: 300,
  headerHeight: 52,
  handleSize: 12,
  borderRadius: 16, // rounded-2xl
} as const;
