import { useTranslation } from 'react-i18next';
import { useApp } from '../context/AppContext';
import { LanguageSwitcher } from './LanguageSwitcher';
import type { LLMProvider } from '../types';

// LLM Provider options
const LLM_PROVIDERS: { id: LLMProvider; name: string }[] = [
  { id: 'deepseek', name: 'DeepSeek' },
  { id: 'openai', name: 'OpenAI' },
];

const LogoIcon = () => (
  <svg className="w-6 h-6" viewBox="0 0 24 24" fill="none">
    <path
      d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M12 3v6a1 1 0 001 1h6"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export function Header() {
  const { focusState, clearFocus, llmProvider, setLlmProvider } = useApp();
  const { t } = useTranslation();

  return (
    <header className="flex-shrink-0 h-14 bg-white border-b border-slate-200 px-4 flex items-center justify-between">
      {/* Left: Logo, title and language switcher */}
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-8 h-8 bg-slate-900 text-white rounded-lg">
          <LogoIcon />
        </div>
        <div>
          <h1 className="text-sm font-semibold text-slate-900">{t('header.title')}</h1>
          <p className="text-xs text-slate-500">{t('header.subtitle')}</p>
        </div>
        <div className="ml-2">
          <LanguageSwitcher />
        </div>
      </div>

      {/* Center: spacer */}
      <div className="flex-1" />

      {/* Right: LLM Provider, Focus mode indicator and actions */}
      <div className="flex items-center gap-3">
        {/* LLM Provider Selector */}
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-slate-500">LLM:</span>
          <select
            value={llmProvider}
            onChange={(e) => setLlmProvider(e.target.value as LLMProvider)}
            className="text-xs px-2 py-1 bg-slate-50 border border-slate-200 rounded-md text-slate-700 hover:bg-slate-100 focus:outline-none focus:ring-1 focus:ring-slate-400 cursor-pointer"
          >
            {LLM_PROVIDERS.map(p => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>

        {focusState.type !== 'none' && (
          <button
            onClick={clearFocus}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-slate-600 bg-amber-50 border border-amber-200 rounded-lg hover:bg-amber-100 transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
            </svg>
            <span>{t('header.focusModeActive')}</span>
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}

      </div>
    </header>
  );
}
