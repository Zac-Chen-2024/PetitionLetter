import { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useApp } from '../context/AppContext';
import { useProject } from '../context/ProjectContext';
import { LanguageSwitcher } from './LanguageSwitcher';
import { projectService, type Project } from '../services/projectService';
import type { LLMProvider, ProjectType } from '../types';
import { toLLMProvider } from '../types';

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
  const { projectId, setProjectId, projectType, projectNumber } = useProject();
  const { t } = useTranslation();

  // Project switcher state
  const [isOpen, setIsOpen] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newType, setNewType] = useState<ProjectType>('EB-1A');
  const [isLoadingList, setIsLoadingList] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown on outside click
  useEffect(() => {
    if (!isOpen) return;
    const handleMouseDown = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleMouseDown);
    return () => document.removeEventListener('mousedown', handleMouseDown);
  }, [isOpen]);

  // Load project list when dropdown opens
  const openDropdown = useCallback(async () => {
    const opening = !isOpen;
    setIsOpen(prev => !prev);
    if (opening) {
      setSearchQuery('');
      setIsCreating(false);
      setIsLoadingList(true);
      try {
        const list = await projectService.list();
        setProjects(list);
      } catch {
        setProjects([]);
      } finally {
        setIsLoadingList(false);
      }
    }
  }, [isOpen]);

  // Select a project
  const handleSelectProject = useCallback((id: string) => {
    setProjectId(id);
    setIsOpen(false);
  }, [setProjectId]);

  // Create a new project
  const handleCreate = useCallback(async () => {
    const name = newName.trim();
    if (!name) return;
    try {
      const created = await projectService.create(name, newType);
      setProjectId(created.id || name);
      setIsOpen(false);
      setNewName('');
      setNewType('EB-1A');
      setIsCreating(false);
    } catch {
      // silent — user can retry
    }
  }, [newName, newType, setProjectId]);

  // Filter projects by search
  const filteredProjects = projects.filter(p =>
    p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    p.id.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const badgeColor = projectType === 'NIW'
    ? 'bg-emerald-100 text-emerald-700'
    : 'bg-blue-100 text-blue-700';

  return (
    <header className="flex-shrink-0 h-14 bg-white border-b border-slate-200 px-4 flex items-center justify-between">
      {/* Left: Project switcher + language switcher */}
      <div className="flex items-center gap-3">
        <div className="flex items-center justify-center w-8 h-8 bg-slate-900 text-white rounded-lg">
          <LogoIcon />
        </div>

        {/* Project switcher */}
        <div className="relative" ref={dropdownRef}>
          <button
            onClick={openDropdown}
            className="flex items-center gap-2 px-2 py-1 -mx-2 rounded-md hover:bg-slate-50 transition-colors"
          >
            <span className="text-sm font-semibold text-slate-900">{projectId}</span>
            <svg
              className={`w-3.5 h-3.5 text-slate-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
            <span className={`text-xs px-2 py-0.5 rounded font-medium ${badgeColor}`}>{projectType}</span>
            {projectNumber && (
              <span className="text-xs text-slate-400">{projectNumber}</span>
            )}
          </button>

          {/* Dropdown panel */}
          {isOpen && (
            <div className="absolute top-full left-0 mt-1 w-72 bg-white border border-slate-200 rounded-lg shadow-lg z-50 overflow-hidden">
              {/* Search */}
              <div className="p-2 border-b border-slate-100">
                <div className="relative">
                  <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                  </svg>
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={e => setSearchQuery(e.target.value)}
                    placeholder={t('header.searchProjects', 'Search projects...')}
                    className="w-full pl-8 pr-3 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-400 focus:border-blue-400"
                    autoFocus
                  />
                </div>
              </div>

              {/* Project list */}
              <div className="max-h-48 overflow-y-auto">
                {isLoadingList ? (
                  <div className="px-3 py-4 text-xs text-slate-400 text-center">Loading...</div>
                ) : filteredProjects.length === 0 ? (
                  <div className="px-3 py-4 text-xs text-slate-400 text-center">
                    {searchQuery ? t('header.noMatchingProjects', 'No matching projects') : t('header.noProjects', 'No projects')}
                  </div>
                ) : (
                  filteredProjects.map(p => {
                    const isCurrent = p.id === projectId || p.name === projectId;
                    const pBadge = p.projectType === 'NIW'
                      ? 'bg-emerald-100 text-emerald-700'
                      : 'bg-blue-100 text-blue-700';
                    return (
                      <button
                        key={p.id}
                        onClick={() => handleSelectProject(p.id || p.name)}
                        className={`w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-slate-50 transition-colors ${
                          isCurrent ? 'bg-blue-50' : ''
                        }`}
                      >
                        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${isCurrent ? 'bg-blue-500' : 'bg-transparent'}`} />
                        <span className={`text-xs truncate flex-1 ${isCurrent ? 'font-semibold text-slate-900' : 'text-slate-700'}`}>
                          {p.name || p.id}
                        </span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium flex-shrink-0 ${pBadge}`}>
                          {p.projectType || 'EB-1A'}
                        </span>
                      </button>
                    );
                  })
                )}
              </div>

              {/* New project */}
              <div className="border-t border-slate-100">
                {!isCreating ? (
                  <button
                    onClick={() => setIsCreating(true)}
                    className="w-full flex items-center gap-2 px-3 py-2 text-xs text-blue-600 hover:bg-blue-50 transition-colors"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                    </svg>
                    {t('header.newProject', 'New project')}
                  </button>
                ) : (
                  <div className="p-3 space-y-2">
                    <input
                      type="text"
                      value={newName}
                      onChange={e => setNewName(e.target.value)}
                      placeholder={t('header.projectName', 'Project name')}
                      className="w-full px-2.5 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-400 focus:border-blue-400"
                      autoFocus
                      onKeyDown={e => { if (e.key === 'Enter') handleCreate(); }}
                    />
                    <div className="flex items-center gap-3">
                      <label className="flex items-center gap-1 text-xs text-slate-600 cursor-pointer">
                        <input
                          type="radio"
                          name="newProjectType"
                          value="EB-1A"
                          checked={newType === 'EB-1A'}
                          onChange={() => setNewType('EB-1A')}
                          className="accent-blue-500"
                        />
                        EB-1A
                      </label>
                      <label className="flex items-center gap-1 text-xs text-slate-600 cursor-pointer">
                        <input
                          type="radio"
                          name="newProjectType"
                          value="NIW"
                          checked={newType === 'NIW'}
                          onChange={() => setNewType('NIW')}
                          className="accent-blue-500"
                        />
                        NIW
                      </label>
                      <div className="flex-1" />
                      <button
                        onClick={() => setIsCreating(false)}
                        className="px-2 py-1 text-xs text-slate-500 hover:text-slate-700"
                      >
                        {t('common.cancel', 'Cancel')}
                      </button>
                      <button
                        onClick={handleCreate}
                        disabled={!newName.trim()}
                        className="px-3 py-1 text-xs font-medium text-white bg-blue-500 rounded-md hover:bg-blue-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                      >
                        {t('common.create', 'Create')}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
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
            onChange={(e) => setLlmProvider(toLLMProvider(e.target.value))}
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
