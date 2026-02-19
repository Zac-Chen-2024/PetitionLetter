import { useApp } from '../context/AppContext';
import type { ViewMode } from '../types';

interface ViewModeOption {
  mode: ViewMode;
  label: string;
  icon: React.ReactNode;
  description: string;
}

const viewModes: ViewModeOption[] = [
  {
    mode: 'line',
    label: 'Line',
    description: 'SVG connection lines',
    icon: (
      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M4 12h4m8 0h4" />
        <circle cx="12" cy="12" r="2" />
        <path d="M8 12c0-2 2-4 4-4s4 2 4 4" strokeDasharray="2 2" />
      </svg>
    ),
  },
  {
    mode: 'sankey',
    label: 'Sankey',
    description: 'Flow diagram',
    icon: (
      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M4 6h2c4 0 4 4 8 4h6" />
        <path d="M4 12h2c4 0 4 4 8 4h6" />
        <path d="M4 18h2c4 0 4-4 8-4h6" />
      </svg>
    ),
  },
];

export function ViewModeSwitcher() {
  const { viewMode, setViewMode } = useApp();

  return (
    <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-lg">
      {viewModes.map((option) => (
        <button
          key={option.mode}
          onClick={() => setViewMode(option.mode)}
          className={`
            flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium
            transition-all duration-200
            ${viewMode === option.mode
              ? 'bg-white text-slate-900 shadow-sm'
              : 'text-slate-600 hover:text-slate-900 hover:bg-slate-50'
            }
          `}
          title={option.description}
        >
          {option.icon}
          <span className="hidden sm:inline">{option.label}</span>
        </button>
      ))}
    </div>
  );
}
